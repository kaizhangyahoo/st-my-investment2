import base64
import json
import os
from googleapiclient import discovery

"""
This script is triggered by a Pub/Sub message containing cost data.
It checks if the cost has exceeded the budget and, if so, disables billing by setting the billing account to an empty string.

Usage:
rename to main.py
$ gcloud functions deploy budget-enforcer --runtime python312 --trigger-topic budget-limit-topic --entry-point limit_cost --project=project-e29b631c-29b0-4dd7-86b
$ gcloud functions call limit_cost --data '{"costAmount": 123.45, "budgetAmount": 100.0}'

To re-enable the project (next month?) 
$ gcloud billing projects link [PROJECT_ID] --billing-account=[BILLING_ACCOUNT]
In this case, the project id is project-e29b631c-29b0-4dd7-86b and the billing account is 016809-C67163-5BE301
"""

def limit_cost(event, context):
    pubsub_data = base64.b64decode(event['data']).decode('utf-8')
    data = json.loads(pubsub_data)
    cost_amount = data['costAmount']
    budget_amount = data['budgetAmount']

    # Check if cost has exceeded the budget
    if cost_amount >= budget_amount:
        project_id = os.environ.get('GCP_PROJECT')
        billing_name = f"projects/{project_id}"
        
        billing = discovery.build('cloudbilling', 'v1', cache_discovery=False)
        
        # This command disables billing by setting the billing account to an empty string
        request = billing.projects().updateBillingInfo(name=billing_name, body={'billingAccountName': ''})
        response = request.execute()
        print(f"Billing disabled for {project_id}: {response}")
