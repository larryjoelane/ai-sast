#!/usr/bin/env python3
"""
Azure OpenAI API Client

Integrates with Azure OpenAI to invoke GPT models (e.g. gpt-4o) for security
scanning and finding validation. Use by setting AI_SAST_LLM=azure and/or
AI_SAST_VALIDATOR_LLM=azure.

Authentication (resolved in this order):
  1. API key  - if AZURE_OPENAI_API_KEY is set.
  2. Entra ID - otherwise, a bearer token via azure-identity
                (DefaultAzureCredential), scope
                https://cognitiveservices.azure.com/.default.

Required configuration:
  AZURE_OPENAI_ENDPOINT      e.g. https://my-resource.openai.azure.com
  AZURE_OPENAI_API_VERSION   e.g. 2024-10-21 (defaults below)
  a deployment name          passed per call (model_name) or via env defaults
"""

import os
from typing import Optional

from openai import AzureOpenAI


# Default Azure OpenAI REST API version (stable GA).
DEFAULT_API_VERSION = "2024-10-21"
# Token scope for Entra ID (AAD) authentication against Azure OpenAI.
AAD_SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureOpenAIClient:
    """
    Client for invoking Azure OpenAI chat-completion deployments.

    Supports API-key auth (AZURE_OPENAI_API_KEY) and, as a fallback, keyless
    Entra ID auth via azure-identity's DefaultAzureCredential.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        deployment: Optional[str] = None,
        api_version: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initialize the Azure OpenAI client.

        Args:
            endpoint: Azure OpenAI resource endpoint
                      (e.g. https://my-resource.openai.azure.com).
                      Defaults to AZURE_OPENAI_ENDPOINT.
            deployment: Default deployment name to use when a call does not
                        pass one. Defaults to AZURE_OPENAI_DEPLOYMENT.
            api_version: REST API version. Defaults to
                         AZURE_OPENAI_API_VERSION or DEFAULT_API_VERSION.
            api_key: Explicit API key. Defaults to AZURE_OPENAI_API_KEY; if
                     absent, Entra ID token auth is used instead.
        """
        self.endpoint = endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT")
        if not self.endpoint:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT is not set. Provide the Azure OpenAI "
                "resource endpoint (e.g. https://my-resource.openai.azure.com)."
            )

        self.deployment = deployment or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        self.api_version = (
            api_version
            or os.environ.get("AZURE_OPENAI_API_VERSION")
            or DEFAULT_API_VERSION
        )

        resolved_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY")

        if resolved_key:
            self._client = AzureOpenAI(
                azure_endpoint=self.endpoint,
                api_key=resolved_key,
                api_version=self.api_version,
            )
            self._auth = "api_key"
        else:
            # Keyless: Entra ID (AAD) bearer token via azure-identity.
            try:
                from azure.identity import (
                    DefaultAzureCredential,
                    get_bearer_token_provider,
                )
            except ImportError as e:
                raise ImportError(
                    "AZURE_OPENAI_API_KEY is not set and azure-identity is not "
                    "installed for Entra ID auth. Either set AZURE_OPENAI_API_KEY "
                    "or run: pip install azure-identity"
                ) from e

            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(), AAD_SCOPE
            )
            self._client = AzureOpenAI(
                azure_endpoint=self.endpoint,
                azure_ad_token_provider=token_provider,
                api_version=self.api_version,
            )
            self._auth = "entra_id"

        print(
            f"✅ Azure OpenAI client initialized "
            f"(endpoint: {self.endpoint}, deployment: {self.deployment}, "
            f"api_version: {self.api_version}, auth: {self._auth})"
        )

    def generate_with_azure(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> str:
        """
        Generate text using an Azure OpenAI chat deployment.

        Args:
            prompt: Input prompt (sent as a single user message).
            model_name: Azure *deployment* name to target. Falls back to the
                        client's default deployment (AZURE_OPENAI_DEPLOYMENT).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature (0.0-1.0).

        Returns:
            Generated text (empty string if the model returns no content).
        """
        deployment = model_name or self.deployment
        if not deployment:
            raise ValueError(
                "No Azure OpenAI deployment specified. Pass model_name or set "
                "AZURE_OPENAI_DEPLOYMENT (or the scan/validator deployment env var)."
            )

        try:
            response = self._client.chat.completions.create(
                model=deployment,  # In Azure, 'model' is the deployment name.
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            print(f"❌ Error invoking Azure OpenAI deployment '{deployment}': {e}")
            raise

        if not response.choices:
            return ""
        return response.choices[0].message.content or ""


def main() -> None:
    """Quick test of the Azure OpenAI client."""
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    client = AzureOpenAIClient(deployment=deployment)

    print("\n🤖 Azure OpenAI - test generation")
    print("-" * 50)
    prompt = "In one sentence, what is the main purpose of a 'hello world' program?"
    try:
        response = client.generate_with_azure(prompt)
        print(f"Prompt: {prompt}")
        print(f"Response: {response}")
    except Exception as e:
        print(f"Error: {e}")
        print(
            "Ensure AZURE_OPENAI_ENDPOINT, a deployment, and either "
            "AZURE_OPENAI_API_KEY or Entra ID credentials are configured."
        )


if __name__ == "__main__":
    main()
