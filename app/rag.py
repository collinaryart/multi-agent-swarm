from __future__ import annotations

import logging
from typing import List, Tuple

import chromadb

logger = logging.getLogger(__name__)


class KnowledgeBase:
    def __init__(
        self,
        persist_directory: str = "./chroma_data",
        collection_name: str = "support_knowledge",
    ) -> None:
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(name=collection_name)

    def seed_default(self) -> None:
        try:
            if self.collection.count() > 0:
                return
        except Exception as exc:
            logger.exception("Failed checking KB collection count: %s", exc)
            return

        ids = ["kb-1", "kb-2", "kb-3", "kb-4"]
        docs = [
            "Password reset issues are usually solved by clearing SSO cache and retrying after 5 minutes.",
            "Billing disputes above 5000 USD must be routed to billing_specialist with invoice references.",
            "If a customer reports suspected account breach, escalate to security_specialist immediately.",
            "Enterprise support SLA: critical tickets target 15 minutes, high 60 minutes, medium 240, low 1440.",
        ]
        sources = ["playbook", "billing-policy", "security-runbook", "sla-policy"]
        try:
            self.collection.add(
                ids=ids,
                documents=docs,
                metadatas=[{"source": source} for source in sources],
            )
        except Exception as exc:
            logger.exception("Failed seeding KB defaults: %s", exc)

    def add_document(self, doc_id: str, content: str, source: str) -> None:
        try:
            self.collection.upsert(
                ids=[doc_id],
                documents=[content],
                metadatas=[{"source": source}],
            )
        except Exception as exc:
            logger.exception("Failed adding KB document %s: %s", doc_id, exc)
            raise

    def search(self, query: str, limit: int = 3) -> List[Tuple[str, str]]:
        try:
            results = self.collection.query(query_texts=[query], n_results=limit)
        except Exception as exc:
            logger.exception("KB search failed for query '%s': %s", query, exc)
            return []
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        output: List[Tuple[str, str]] = []
        for doc, meta in zip(documents, metadatas):
            source = (meta or {}).get("source", "unknown")
            output.append((source, doc))
        return output
