import pandas as pd
from django.core.management.base import BaseCommand
from api.models import Customer, Loan
from django.db import transaction
from datetime import datetime

class Command(BaseCommand):
    help = 'Ingest data from Excel files'

    def handle(self, *args, **options):
        self.ingest_customer_data()
        self.ingest_loan_data()

    @transaction.atomic
    def ingest_customer_data(self):
        df = pd.read_excel('customer_data.xlsx')
        created_count = 0
        updated_count = 0
        for _, row in df.iterrows():
            customer, created = Customer.objects.update_or_create(
                customer_id=row['Customer ID'],
                defaults={
                    'first_name': row['First Name'],
                    'last_name': row['Last Name'],
                    'age': row['Age'],
                    'phone_number': str(row['Phone Number']),
                    'monthly_salary': row['Monthly Salary'],
                    'approved_limit': row['Approved Limit']
                }
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
        self.stdout.write(self.style.SUCCESS(f'Successfully ingested {created_count} new customer records and updated {updated_count} existing records'))

    @transaction.atomic
    def ingest_loan_data(self):
        df = pd.read_excel('loan_data.xlsx')
        created_count = 0
        for _, row in df.iterrows():
            try:
                customer = Customer.objects.get(customer_id=row['Customer ID'])
                Loan.objects.update_or_create(
                    loan_id=row['Loan ID'],
                    defaults={
                        'customer': customer,
                        'loan_amount': row['Loan Amount'],
                        'tenure': row['Tenure'],
                        'interest_rate': row['Interest Rate'],
                        'monthly_payment': row['Monthly payment'],
                        'emis_paid_on_time': row['EMIs paid on Time'],
                        'start_date': row['Date of Approval'].to_pydatetime().date(),
                        'end_date': row['End Date'].to_pydatetime().date()
                    }
                )
                created_count += 1
            except Customer.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Customer with ID {row['Customer ID']} does not exist. Skipping loan record."))
        self.stdout.write(self.style.SUCCESS(f'Successfully ingested {created_count} loan records'))