import time
import uuid
import httpx
import openpyxl
import os
from dotenv import load_dotenv
from tqdm import tqdm


load_dotenv(override=True)

API_URL = os.getenv("API_URL", "")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
SLEEP_SECONDS = 5
HAIKU = os.getenv("HAIKU")
SONNET_V1 = os.getenv("SONNET_V1")
SONNET_V2 = os.getenv("SONNET_V2")
SONNET_37 = os.getenv("SONNET_37")
SONNET_45 = os.getenv("SONNET_45")
OPUS_3_V1 = os.getenv("OPUS_3_V1")

MODEL_NAME = "SONNET_45"
MODEL_ID = SONNET_45
RUN_COUNT = 3

question_sets = {
    "General": [
        # "Who is the local lawyer for CAMCAR?",
        # "what are AZ's standard publication terms?",
        # "who is the AZ lawyer for Italy?",
        # "what template do I use for AZ to license software?",
        # "can I use the Terms and Conditions as a framework agreement. (Guidance says this contract cannot be used for multiple purchases).",
        # "when do I need to include a cyber security appendix with an MSA (Guidance explains the requirements).",
        # "are there any specific payment terms within the EU or do the same ones apply across all Member States?",
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
}

EXCEL_FILE = "qna_model_comparison.xlsx"

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
        }
    }
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

def get_or_create_sheet():
    if os.path.exists(EXCEL_FILE):
        wb = openpyxl.load_workbook(EXCEL_FILE)
        ws = wb.active
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "QnA Model Comparison"
        ws.append(["Set", "Question"])  # Start with Set and Question columns
    return wb, ws

def find_question_row(ws, set_name, question):
    for row in ws.iter_rows(min_row=2, values_only=False):
        if row[0].value == set_name and row[1].value == question:
            return row[0].row
    return None

def main():
    wb, ws = get_or_create_sheet()

    # Find where to add new columns
    existing_headers = [cell.value for cell in ws[1]]
    new_headers = []
    for i in range(1, RUN_COUNT + 1):
        col_name = f"{MODEL_NAME}" if RUN_COUNT == 1 else f"{MODEL_NAME}_{i}"
        new_headers.append(col_name)
        if col_name not in existing_headers:
            ws.cell(row=1, column=len(existing_headers) + 1, value=col_name)
            existing_headers.append(col_name)
    # Calculate total iterations for tqdm
    total_questions = sum(len(qs) for qs in question_sets.values())
    total_iterations = total_questions * RUN_COUNT

    with tqdm(total=total_iterations, desc="Processing QnA", ncols=100) as pbar:
        for set_name, questions in question_sets.items():
            for q in questions:
                # Find or create the row for this question
                row_num = find_question_row(ws, set_name, q)
                if not row_num:
                    ws.append([set_name, q])
                    row_num = ws.max_row

                for i in range(1, RUN_COUNT + 1):
                    answer = ""
                    result = ask_question(q, set_name, MODEL_ID)
                    answer = result.get("result", {}).get("answer", {}).get("ans", "")
                    if not answer:
                        answer = "[No answer returned or error]"
                    col_name = f"{MODEL_NAME}" if RUN_COUNT == 1 else f"{MODEL_NAME}_{i}"
                    col_idx = existing_headers.index(col_name) + 1
                    ws.cell(row=row_num, column=col_idx, value=answer)
                    print(f"[{set_name}] Q: {q}\nA: {answer}\nModel: {col_name}\n{'-'*60}")
                    time.sleep(SLEEP_SECONDS)
                    pbar.update(1)

        wb.save(EXCEL_FILE)
        print(f"Results saved to {EXCEL_FILE}")

if __name__ == "__main__":
    main()