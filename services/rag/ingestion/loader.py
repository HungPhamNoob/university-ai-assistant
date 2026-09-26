# ============================================
# services/rag/ingestion/loader.py
# ============================================
"""
Document loading utilities for the ingestion pipeline.
"""

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document


def load_pdf(file_path: str) -> list[Document]:
    """
    Load a PDF file and return its pages as LangChain Documents.

    Args:
        file_path: Path to the PDF file.

    Returns:
        List of Document objects.
    """
    loader = PyPDFLoader(file_path)
    return loader.load()
