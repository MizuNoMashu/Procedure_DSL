# src/document_processor/chunker.py
"""
Text chunking utilities.
"""

from typing import List

class TextChunk:
    """Container for text chunk"""
    def __init__(self, text: str, index: int, metadata: dict = None):
        self.text = text
        self.index = index
        self.metadata = metadata or {}
    
    def __repr__(self):
        return f"Chunk({self.index}, chars={len(self.text)})"

class TextChunker:
    """Split text into chunks"""
    
    def __init__(self, chunk_size: int = None, chunk_overlap: int = None):
        """
        Args:
            chunk_size: Characters per chunk (None = use config or default 1000)
            chunk_overlap: Overlap between chunks (None = use config or default 100)
        """
        if chunk_size is None or chunk_overlap is None:
            try:
                from flask import current_app
                config = current_app.config.get('RAG_CONFIG') or current_app.config.get('PIPELINE_CONFIG', {})
                chunk_size = chunk_size or config.get('chunking', {}).get('size', 1000)
                chunk_overlap = chunk_overlap or config.get('chunking', {}).get('overlap', 100)
            except (RuntimeError, ImportError):
                # No Flask installed or no active app context — use defaults
                chunk_size = chunk_size or 1000
                chunk_overlap = chunk_overlap or 100

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    def split(self, text: str, metadata: dict = None) -> List[TextChunk]:
        """
        Split text into overlapping chunks.
        
        Args:
            text: Text to split
            metadata: Optional metadata to attach to chunks
        
        Returns:
            List of TextChunk objects
        """
        chunks = []
        start = 0
        index = 0
        
        while start < len(text):
            # End position for this chunk
            end = start + self.chunk_size
            
            # Extract chunk
            chunk_text = text[start:end]
            
            # Create chunk object
            chunk = TextChunk(
                text=chunk_text.strip(),
                index=index,
                metadata={
                    **(metadata or {}),
                    'start': start,
                    'end': end,
                    'chunk_size': self.chunk_size,
                    'overlap': self.chunk_overlap
                }
            )
            
            chunks.append(chunk)
            
            # Move to next chunk with overlap
            start += self.chunk_size - self.chunk_overlap
            index += 1
        
        return chunks
    
    def split_by_separator(self, text: str, separator: str = "\n\n", metadata: dict = None) -> List[TextChunk]:
        """
        Split text by separator (e.g., paragraphs).
        Then merge small chunks to reach chunk_size.
        
        Args:
            text: Text to split
            separator: Separator to use
            metadata: Optional metadata
        
        Returns:
            List of TextChunk objects
        """
        # Split by separator
        parts = text.split(separator)
        
        chunks = []
        current_chunk = ""
        index = 0
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # If adding this part exceeds chunk_size, save current chunk
            if len(current_chunk) + len(part) > self.chunk_size and current_chunk:
                chunks.append(TextChunk(
                    text=current_chunk.strip(),
                    index=index,
                    metadata=metadata
                ))
                current_chunk = part
                index += 1
            else:
                # Add to current chunk
                if current_chunk:
                    current_chunk += separator + part
                else:
                    current_chunk = part
        
        # Add last chunk
        if current_chunk:
            chunks.append(TextChunk(
                text=current_chunk.strip(),
                index=index,
                metadata=metadata
            ))
        
        return chunks