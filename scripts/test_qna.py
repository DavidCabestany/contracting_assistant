import time
import uuid
import httpx
import openpyxl
import os
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("API_URL", "")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
SLEEP_SECONDS = 5
HAIKU = os.getenv("HAIKU")
SONNET_V1 = os.getenv("SONNET_V1")
SONNET_V2 = os.getenv("SONNET_V2")
SONNET_37 = os.getenv("SONNET_37")
SONNET_45 = os.getenv("SONNET_45")
OPUS_3_V1 = os.getenv("OPUS_3_V1")

MODEL_IDS = [
    HAIKU,
    SONNET_V1,
    SONNET_V2,
    SONNET_37,
    SONNET_45,
    OPUS_3_V1,
]
# Define your question sets
question_sets = {
    "General": [
        "Who is the local lawyer for CAMCAR?",
        "what are AZ's standard publication terms?",
        "who is the AZ lawyer for Italy?",
        "what template do I use for AZ to license software?",
        "can I use the Terms and Conditions as a framework agreement. (Guidance says this contract cannot be used for multiple purchases).",
        "when do I need to include a cyber security appendix with an MSA (Guidance explains the requirements).",
        "are there any specific payment terms within the EU or do the same ones apply across all Member States?",
        "what is CCT Team?",
        "how is the length of the payment term determined?",
        "how should I proceed if I need a signature on my agreement?",
        "What can CCT do for me?",
        "Where can I seek information or guidance about contract templates?",
        'what modifications I can make within the "Expectations of Third Parties" clause if the contract is concluded by a Supplier being one individual who has no employees?',
        "what is the difference between a warranty and an undertaking?",
        "can we agree to limit Supplier's liability for wilful misconduct?",
        "what is a handbook?",
        "what can I use CAN Handbook for",
        "What is AZ's position in relation to the indemnification language that is acceptable from AZ's point of view in scenarios where AZ is the sponsor of a study?",
        "What is AZ's position on choosing the State of California US as the seat of dispute resolution for a Master Services Agreement?",
        "What is AZ's position when a supplier requests to be named on AZ's insurance policy?",
        "At AZ, how long are CDAs expected to be in force for?",
        "Is it okay to accept late payment terms proposed by a supplier?",
        "Can we accept payment of interest as a penalty on overdue invoices?",
        "Can CCT tell me who can sign my contract?",
        "Can I use a Supplier's template for a non-disclosure agreement?",
        "What is the meaning of Novation?",
        "how do I pick the correct data protection terms?",
        "can AZ agree to pay the costs of an audit?",
    ],
    "Privacy": [
        "Can I agree to changing Clause 1.4?",
        "We need to confirm what kind of Exhibit we need to add to an Agreement. This is about Medical Communications, which involves publications. The vendor is an Institution, and they have a database of clinical trials and patient data.",
        "Is anonymized data personal data?",
        "what template should I use when both parties are controllers?",
        "What about when I process data of Chinese individuals? Which template to use?",
        "Can I agree to limiting the time for AZ to object to appointment of Subprocessor?",
        "Can I agree to extend deadline for the Supplier to delete personal data after expiration of the agreement?",
        "Can I agree to changing the definition to the following wording: “Anonymised Data” data which does not itself identify any individual and which will not allow any individual to be re-identified, whether through its combination with other data held by an authorised party or otherwise;",
        "Which template clarifies what all the other templates govern and when they are used?",
        "What kind of template should I use when clinical data is in scope? AZ sponsors the clinical trial, and we decide on how the sample will be used.",
    ],
    # Add more sets as needed
}

def ask_question(question, knowledge_type, model_id):
    payload = {
        "apiKey": "",
        "user": {
            "id": "ktmb950",
            "sessionId": str(uuid.uuid4()),
            "language": "us-en",
            "platform": "web",
        },
        "query": {
            "text": question,
            "knowledgeType": knowledge_type,
            "transactionCount": 0,
            "files": [],
        }}
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(API_URL, json=payload, headers=headers, timeout=180)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error for model {model_id}, question '{question}': {e}")
        return {}

def main():
    count = 3  # Number of times to repeat each question/model
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "QnA Model Comparison"
    ws.append(["Set", "Question", "Model ID", "Answer", "Citations"])
    model_id = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # Sonnet 4.5
    for set_name, questions in question_sets.items():
        for i in range(count):
            for q in questions:
                    print(f"Asking: [{set_name}] {q} (Model: {model_id})")
                    result = ask_question(q, set_name, model_id)
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
                    print(f"[{set_name}] Q: {q}\nA: {answer}\nModel: {model_id}\nCitations: {citations_str}\n{'-'*60}")
                    
                    ws.append([set_name, q, model_id, answer, citations_str])
                    time.sleep(5)

    wb.save("qna_model_comparison.xlsx")
    print("Results saved to qna_model_comparison.xlsx")

if __name__ == "__main__":
    main()