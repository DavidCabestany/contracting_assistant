
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError

load_dotenv()


def _get_env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def main() -> int:
    endpoint = _get_env(
        "AZURE_OPENAI_ENDPOINT").rstrip("/")
    api_key = _get_env("AZURE_OPENAI_API_KEY")
    deployment = _get_env("AZURE_OPENAI_DEPLOYMENT", "gpt-5")

    client = OpenAI(
        api_key=api_key,
        base_url=f"{endpoint}/openai/v1/",
    )

    print(f"Endpoint:   {endpoint}/openai/v1/")
    print(f"Deployment: {deployment}")

    # try:
        # models = client.models.list()
        # model_ids = [m.id for m in getattr(models, "data", [])]
        # print(f"models.list OK ({len(model_ids)} models returned)")
        # if model_ids:
        #     print("First 10:", model_ids[:10])
    # except APIStatusError as e:
    #     print("models.list blocked/failed (often due to permissions). Continuing...")
    #     print(f"HTTP {e.status_code}: {e.response.text}")
    # except Exception as e:
    #     print("models.list failed. Continuing...")
    #     print(repr(e))

    try:
        resp = client.responses.create(
            model=deployment, 
            input="Tell me a joke about developers.",
            max_output_tokens=20000,
        )
        print("\n responses.create OK")
        print(resp.output_text)
        return 0

    except APIStatusError as e:
        print("\n responses.create failed (APIStatusError)")
        print(f"HTTP {e.status_code}: {e.response.text}")
        return 1

    except Exception as e:
        print("\n responses.create failed")
        print(repr(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
