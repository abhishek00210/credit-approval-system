from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Customer, Loan
from .serializers import CustomerSerializer, LoanSerializer
from django.db.models import Sum
from datetime import date
from django.shortcuts import render

@api_view(['POST'])
def register(request):
    serializer = CustomerSerializer(data=request.data)
    if serializer.is_valid():
        monthly_income = serializer.validated_data['monthly_income']
        approved_limit = round(36 * monthly_income, -5)  # Rounded to nearest lakh
        serializer.save(approved_limit=approved_limit)
        return Response({
            'customer_id': serializer.instance.id,
            'name': f"{serializer.instance.first_name} {serializer.instance.last_name}",
            'age': serializer.instance.age,
            'monthly_income': serializer.instance.monthly_income,
            'approved_limit': approved_limit,
            'phone_number': serializer.instance.phone_number
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
def check_eligibility(request):
    customer_id = request.data.get('customer_id')
    loan_amount = request.data.get('loan_amount')
    interest_rate = request.data.get('interest_rate')
    tenure = request.data.get('tenure')

    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return Response({"error": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)

    credit_score = calculate_credit_score(customer)
    
    current_loans = Loan.objects.filter(customer=customer, end_date__gte=date.today())
    current_emis = current_loans.aggregate(total_emi=Sum('monthly_repayment'))['total_emi'] or 0

    if current_emis > 0.5 * customer.monthly_income:
        return Response({
            "customer_id": customer_id,
            "approval": False,
            "interest_rate": interest_rate,
            "corrected_interest_rate": interest_rate,
            "tenure": tenure,
            "monthly_installment": 0
        })

    if credit_score > 50:
        approval = True
    elif 50 >= credit_score > 30:
        approval = interest_rate > 12
        interest_rate = max(interest_rate, 12)
    elif 30 >= credit_score > 10:
        approval = interest_rate > 16
        interest_rate = max(interest_rate, 16)
    else:
        approval = False

    monthly_installment = (loan_amount * (1 + interest_rate/100) ** (tenure/12)) / tenure if approval else 0

    return Response({
        "customer_id": customer_id,
        "approval": approval,
        "interest_rate": interest_rate,
        "corrected_interest_rate": interest_rate,
        "tenure": tenure,
        "monthly_installment": round(monthly_installment, 2)
    })

@api_view(['POST'])
def create_loan(request):
    customer_id = request.data.get('customer_id')
    loan_amount = request.data.get('loan_amount')
    interest_rate = request.data.get('interest_rate')
    tenure = request.data.get('tenure')

    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return Response({"error": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)

    eligibility_check = check_eligibility(request._request)
    if eligibility_check.data['approval']:
        monthly_installment = eligibility_check.data['monthly_installment']
        loan = Loan.objects.create(
            customer=customer,
            loan_amount=loan_amount,
            interest_rate=interest_rate,
            tenure=tenure,
            monthly_repayment=monthly_installment,
            emis_paid_on_time=0,
            start_date=date.today(),
            end_date=date.today().replace(year=date.today().year + tenure//12, month=date.today().month + tenure%12)
        )
        return Response({
            "loan_id": loan.id,
            "customer_id": customer_id,
            "loan_approved": True,
            "message": "Loan approved",
            "monthly_installment": monthly_installment
        })
    else:
        return Response({
            "loan_id": None,
            "customer_id": customer_id,
            "loan_approved": False,
            "message": "Loan not approved",
            "monthly_installment": 0
        })

@api_view(['GET'])
def view_loan(request, loan_id):
    try:
        loan = Loan.objects.get(id=loan_id)
    except Loan.DoesNotExist:
        return Response({"error": "Loan not found"}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        "loan_id": loan.id,
        "customer": {
            "id": loan.customer.id,
            "first_name": loan.customer.first_name,
            "last_name": loan.customer.last_name,
            "phone_number": loan.customer.phone_number,
            "age": loan.customer.age
        },
        "loan_amount": loan.loan_amount,
        "interest_rate": loan.interest_rate,
        "monthly_installment": loan.monthly_repayment,
        "tenure": loan.tenure
    })

@api_view(['GET'])
def view_loans_by_customer(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return Response({"error": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)

    loans = Loan.objects.filter(customer=customer)
    loan_data = []

    for loan in loans:
        loan_data.append({
            "loan_id": loan.id,
            "loan_amount": loan.loan_amount,
            "interest_rate": loan.interest_rate,
            "monthly_installment": loan.monthly_repayment,
            "repayments_left": calculate_repayments_left(loan)
        })

    return Response(loan_data)

def calculate_credit_score(customer):
    loans = Loan.objects.filter(customer=customer)
    
    if not loans:
        return 50  # Default score for new customers

    total_loans = loans.count()
    loans_paid_on_time = loans.filter(emis_paid_on_time=loans.first().tenure).count()
    loans_with_current_year_activity = loans.filter(start_date__year=date.today().year).count()
    
    credit_score = 0
    
    # Past loans paid on time
    credit_score += (loans_paid_on_time / total_loans) * 20
    
    # Number of loans taken in the past
    if total_loans <= 2:
        credit_score += 20
    elif total_loans <= 5:
        credit_score += 10
    
    # Loan activity in the current year
    credit_score += min(loans_with_current_year_activity * 5, 20)
    
    # Loan approved volume
    total_loan_amount = sum(loan.loan_amount for loan in loans)
    if total_loan_amount <= customer.approved_limit:
        credit_score += 20
    elif total_loan_amount <= customer.approved_limit * 2:
        credit_score += 10
    
    # Check if sum of current loans > approved limit
    current_loans = loans.filter(end_date__gte=date.today())
    current_loan_sum = sum(loan.loan_amount for loan in current_loans)
    if current_loan_sum > customer.approved_limit:
        return 0
    
    return min(credit_score, 100)

def calculate_repayments_left(loan):
    months_passed = (date.today().year - loan.start_date.year) * 12 + date.today().month - loan.start_date.month
    return max(0, loan.tenure - months_passed)


def dashboard(request):
    customers = Customer.objects.all()[:10]  # Get first 10 customers
    loans = Loan.objects.all()[:10]  # Get first 10 loans
    return render(request, 'api/dashboard.html', {'customers': customers, 'loans': loans})