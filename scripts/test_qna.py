"""Test script for batch querying the QnA API endpoint.

This script sends a set of questions multiple times to the FastAPI QnA endpoint,
collects answers and citations, and writes the results to an Excel file for analysis.
It is useful for load testing, regression testing, and validating API responses.
"""

import time
import uuid

import httpx
import openpyxl

API_URL = "http://127.0.0.1:8000/getqnaanswer/"
AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLVVJIiwiZXhwIjoxNzYzNzExMDU0fQ.jvNYk0kw7VLSXwBH28n71-9VMqKbZJNqVtdizhb_334"

questions = [
    "are there any specific payment terms within the EU or do the same ones apply across all Member States?",
    "are there any specific payment terms within the European Union or do the same ones apply in all Member States?",
]

# Additional question sets (Privacy, General Queries) are commented out for reference.

# Privacy
# "Can I agree to changing Clause 1.4?",
# "We need to confirm what kind of Exhibit we need to add to an Agreement. This is about Medical Communications, which involves publications. The vendor is an Institution, and they have a database of clinical trials and patient data.",
# "Is anonymized data personal data?",
# "what template should I use when both parties are controllers?",
# "What about when I process data of Chinese individuals? Which template to use?",
# "Can I agree to limiting the time for AZ to object to appointment of Subprocessor?",
# "Can I agree to extend deadline for the Supplier to delete personal data after expiration of the agreement?",
# "Can I agree to changing the definition to the following wording: “Anonymised Data” data which does not itself identify any individual and which will not allow any individual to be re-identified, whether through its combination with other data held by an authorised party or otherwise;",
# "Which template clarifies what all the other templates govern and when they are used?",
# "What kind of template should I use when clinical data is in scope? AZ sponsors the clinical trial, and we decide on how the sample will be used.",


# General Queries
# "Who is the local lawyer for CAMCAR?",
# "what are AZ's standard publication terms?",
# "who is the AZ lawyer for Italy?",
# "what template do I use for AZ to license software?",
# "can I use the Terms and Conditions as a framework agreement. (Guidance says this contract cannot be used for multiple purchases).",
# "when do I need to include a cyber security appendix with an MSA (Guidance explains the requirements).",
# "are there any specific payment terms within the EU or do the same ones apply across all Member States?",
# "what is CCT Team?",
# "how is the length of the payment term determined?",
# "how should I proceed if I need a signature on my agreement?",
# "What can CCT do for me?",
# "Where can I seek information or guidance about contract templates?",
# 'what modifications I can make within the "Expectations of Third Parties" clause if the contract is concluded by a Supplier being one individual who has no employees?',
# "what is the difference between a warranty and an undertaking?",
# "can we agree to limit Supplier's liability for wilful misconduct?",
# "what is a handbook?",
# "what can I use CAN Handbook for",
# "What is AZ's position in relation to the indemnification language that is acceptable from AZ's point of view in scenarios where AZ is the sponsor of a study?",
# "What is AZ's position on choosing the State of California US as the seat of dispute resolution for a Master Services Agreement?",
# "What is AZ's position when a supplier requests to be named on AZ's insurance policy?",
# "At AZ, how long are CDAs expected to be in force for?",
# "Is it okay to accept late payment terms proposed by a supplier?",
# "Can we accept payment of interest as a penalty on overdue invoices?",
# "Can CCT tell me who can sign my contract?",
# "Can I use a Supplier's template for a non-disclosure agreement?",
# "What is the meaning of Novation?",
# "how do I pick the correct data protection terms?",
# "can AZ agree to pay the costs of an audit?",


def ask_question(question):
    """Send a single question to the QnA API and return the response as JSON.

    Args:
        question (str): The question to be asked.

    Returns:
        dict: The JSON response from the API.
    """
    payload = {
        "apiKey": "",
        "user": {
            "id": "ktmb950",
            "sessionId": str(uuid.uuid4()),  # New session for each question
            "language": "us-en",
            "platform": "web",
        },
        "query": {
            "text": question,
            "knowledgeType": "general queries",
            "transactionCount": 0,
            "files": [],
        },
    }
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }
    response = httpx.post(API_URL, json=payload, headers=headers, timeout=180)
    return response.json()


def main():
    """Run the batch test by sending each question multiple times and saving results to Excel.

    Steps:
        1. Initialize an Excel workbook.
        2. Loop through each question multiple times.
        3. Send the question to the API and collect the answer and citations.
        4. Append results to the Excel sheet.
        5. Save the workbook to a file.
    """
    count = 5
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "QnA Results"
    ws.append(["Question", "Answer", "Citations"])

    for i in range(count):
        for q in questions:
            print(f"Asking: {q}")
            result = ask_question(q)
            answer = result.get("result", {}).get("answer", {}).get("ans", "")
            citations = result.get("result", {}).get("citations", [])
            citations_str = (
                "; ".join(
                    f"{c.get('fileName', '')} (Page {c.get('pageNumber', '')})"
                    for c in citations
                )
                if citations
                else "None"
            )
            ws.append([q, answer, citations_str])
            time.sleep(10)

    wb.save("EU_qna_results.xlsx")
    print("Results saved to EU_qna_results.xlsx")


if __name__ == "__main__":
    main()
