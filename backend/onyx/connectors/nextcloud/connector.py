"""
Nextcloud connector for Onyx using WebDAV API.
"""

import io
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput, LoadConnector, PollConnector
from onyx.connectors.models import Document, TextSection
from onyx.file_processing.extract_file_text import extract_text_and_images

from .client import NextcloudWebDAVClient

logger = logging.getLogger(__name__)

# Type aliases
SecondsSinceUnixEpoch = float

# Constants
INDEX_BATCH_SIZE = 50

# File extension filter for acceptable file types
ACCEPTED_FILE_EXTENSIONS = {
    '.txt', '.md', '.pdf', '.doc', '.docx', '.ppt', '.pptx', 
    '.xls', '.xlsx', '.csv', '.rtf', '.html', '.htm', '.xml',
    '.json', '.py', '.js', '.css', '.java', '.cpp', '.c', '.h'
}


class ConnectorMissingCredentialError(Exception):
    """Exception raised when connector credentials are missing or invalid."""
    pass


def is_accepted_file_ext(file_path: str, accepted_extensions: set = None) -> bool:
    """Check if file extension is supported."""
    if accepted_extensions is None:
        accepted_extensions = ACCEPTED_FILE_EXTENSIONS
    
    ext = file_path.lower().split('.')[-1] if '.' in file_path else ''
    return f'.{ext}' in accepted_extensions


class NextcloudConnector(LoadConnector, PollConnector):
    """Connector for indexing files from Nextcloud instances via WebDAV."""
    
    def __init__(
        self,
        server_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        path_filter: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        verify_ssl: bool = True,
        file_extensions: List[str] | None = None,
    ) -> None:
        """Initialize the Nextcloud connector.
        
        Args:
            server_url: Nextcloud server URL
            username: Nextcloud username  
            password: Nextcloud password or app token
            path_filter: Optional path to limit indexing scope
            batch_size: Number of documents to process in each batch
            verify_ssl: Whether to verify SSL certificates
            file_extensions: Optional list of file extensions to include (e.g., ['.txt', '.pdf'])
        """
        self.server_url = server_url
        self.username = username 
        self.password = password
        self.path_filter = path_filter or ""
        self.batch_size = batch_size
        self.verify_ssl = verify_ssl
        self.file_extensions = set(file_extensions) if file_extensions else ACCEPTED_FILE_EXTENSIONS
        
        self._client: Optional[NextcloudWebDAVClient] = None

    def load_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any] | None:
        """Load credentials for accessing Nextcloud.
        
        Args:
            credentials: Dictionary containing authentication credentials
            
        Returns:
            None
        """
        self.server_url = credentials["nextcloud_server_url"]
        self.username = credentials["nextcloud_username"]
        self.password = credentials["nextcloud_password"]

        # Optional configuration from connector config (not credentials)
        self.path_filter = credentials.get("path_filter", "")
        self.verify_ssl = credentials.get("verify_ssl", True)
        
        # Handle file extensions
        file_extensions = credentials.get("file_extensions", [])
        if file_extensions:
            # Ensure extensions start with a dot
            self.file_extensions = set(
                ext if ext.startswith('.') else f'.{ext}' 
                for ext in file_extensions
            )
        else:
            self.file_extensions = ACCEPTED_FILE_EXTENSIONS
        
        # Reset client to force recreation with new credentials
        self._client = None
        
        return None

    @property
    def client(self) -> NextcloudWebDAVClient:
        """Get or create WebDAV client instance."""
        if self._client is None:
            if not all([self.server_url, self.username, self.password]):
                raise ConnectorMissingCredentialError("Nextcloud")
            
            self._client = NextcloudWebDAVClient(
                server_url=self.server_url,
                username=self.username, 
                password=self.password,
                verify_ssl=self.verify_ssl,
            )
        
        return self._client

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all accessible files from Nextcloud.
        
        Yields:
            Batches of Document objects
        """
        yield from self._get_all_documents()

    def poll_source(
        self, 
        start: SecondsSinceUnixEpoch, 
        end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Load files modified within the specified time range.
        
        Args:
            start: Start timestamp 
            end: End timestamp
            
        Yields:
            Batches of Document objects
        """
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc) 
        
        yield from self._get_all_documents(modified_since=start_datetime)

    def _get_all_documents(
        self,
        modified_since: Optional[datetime] = None
    ) -> GenerateDocumentsOutput:
        """Get all documents, optionally filtered by modification date.

        Traverses directories incrementally and yields batches as files are found,
        providing progress visibility for large Nextcloud instances.

        Args:
            modified_since: Only include files modified after this date

        Yields:
            Batches of Document objects
        """
        try:
            logger.info(f"Starting incremental traversal from path: '{self.path_filter}'")

            doc_batch: List[Document] = []
            directories_to_process = [self.path_filter]
            processed_dirs: set = set()
            total_files_found = 0
            total_docs_created = 0

            while directories_to_process:
                current_path = directories_to_process.pop(0)

                # Skip if already processed
                if current_path in processed_dirs:
                    continue
                processed_dirs.add(current_path)

                try:
                    # List items in current directory (depth=1 for reliability)
                    items = self.client.list_files(path=current_path, depth="1")

                    files_in_dir = 0
                    subdirs_in_dir = 0

                    for item in items:
                        item_path = item.get('path', '')

                        # Skip the directory itself
                        if item_path.rstrip('/') == current_path.rstrip('/') or item_path == '/':
                            continue

                        if item.get('is_directory', False):
                            directories_to_process.append(item_path)
                            subdirs_in_dir += 1
                        else:
                            files_in_dir += 1
                            total_files_found += 1

                            # Apply date filter
                            if modified_since and item.get('last_modified'):
                                if item['last_modified'] < modified_since:
                                    continue

                            # Check if file type is supported
                            if not self._is_supported_file(item):
                                continue

                            # Create document from file
                            try:
                                document = self._create_document_from_file(item)
                                if document:
                                    doc_batch.append(document)
                                    total_docs_created += 1

                                    # Yield batch when full
                                    if len(doc_batch) >= self.batch_size:
                                        logger.info(f"Yielding batch of {len(doc_batch)} docs (total: {total_docs_created} docs from {total_files_found} files, {len(processed_dirs)} dirs)")
                                        yield doc_batch
                                        doc_batch = []
                            except Exception as e:
                                logger.error(f"Error processing file {item_path}: {e}")
                                continue

                    logger.info(f"Dir '{current_path}': {files_in_dir} files, {subdirs_in_dir} subdirs. Queue: {len(directories_to_process)}. Total: {total_files_found} files, {total_docs_created} docs")

                except Exception as e:
                    logger.warning(f"Failed to list '{current_path}': {e}. Continuing...")
                    continue

            # Yield remaining documents
            if doc_batch:
                logger.info(f"Yielding final batch of {len(doc_batch)} docs (total: {total_docs_created} from {total_files_found} files)")
                yield doc_batch

            logger.info(f"Traversal complete: {len(processed_dirs)} dirs, {total_files_found} files, {total_docs_created} docs indexed")

        except Exception as e:
            logger.error(f"Error getting documents from Nextcloud: {e}")
            raise

    def _create_document_from_file(self, file_info: Dict[str, Any]) -> Optional[Document]:
        """Create a Document object from Nextcloud file information.

        Uses Onyx's extract_text_and_images for proper extraction from
        PDFs, DOCs, and other file formats.

        Args:
            file_info: File information dictionary from WebDAV response

        Returns:
            Document object or None if creation fails
        """
        try:
            file_path = file_info.get('path', '')
            file_name = file_info.get('name') or file_path.split('/')[-1]

            # Get file content
            try:
                file_content = self.client.get_file_content(file_path)

                # Use Onyx's file processing for proper text extraction (PDF, DOC, etc.)
                file_obj = io.BytesIO(file_content)
                extraction_result = extract_text_and_images(
                    file=file_obj,
                    file_name=file_name,
                )

                extracted_text = extraction_result.text_content

                if not extracted_text or not extracted_text.strip():
                    logger.debug(f"No text extracted from {file_path}")
                    return None

            except Exception as e:
                logger.warning(f"Failed to extract content from {file_path}: {e}")
                return None

            # Create document sections
            file_id = file_info.get('file_id', '')
            sections = [TextSection(
                link=self._build_file_url(file_path, file_id),
                text=extracted_text,
            )]

            # Build metadata
            metadata = self._build_metadata(file_info)

            # Add any metadata from the extraction (e.g., PDF metadata)
            if extraction_result.metadata:
                for key, value in extraction_result.metadata.items():
                    if key not in metadata:
                        metadata[key] = str(value)

            # Create document
            document = Document(
                id=f"nextcloud_{file_info.get('file_id', file_path)}",
                sections=sections,
                source=DocumentSource.NEXTCLOUD,
                semantic_identifier=file_name,
                doc_updated_at=file_info.get('last_modified'),
                metadata=metadata,
            )

            return document

        except Exception as e:
            logger.error(f"Error creating document from file {file_info.get('path', 'unknown')}: {e}")
            return None

    def _build_file_url(self, file_path: str, file_id: str = "") -> str:
        """Build a URL to view the file in Nextcloud web interface.

        Args:
            file_path: Path to the file
            file_id: Nextcloud file ID (from WebDAV oc:fileid)

        Returns:
            Web URL for the file (properly URL-encoded)
        """
        # Ensure the path starts with a slash
        if not file_path.startswith('/'):
            file_path = '/' + file_path

        # URL-encode the directory path to handle spaces and special chars
        dir_path = quote(os.path.dirname(file_path), safe='/')

        # Nextcloud URL format: /apps/files/files/{file_id}?dir=...&editing=false&openfile=true
        if file_id:
            return f"{self.server_url}/apps/files/files/{file_id}?dir={dir_path}&editing=false&openfile=true"
        else:
            # Fallback without file_id (won't open the file directly)
            return f"{self.server_url}/apps/files/?dir={dir_path}&editing=false&openfile=true"

    def _build_metadata(self, file_info: Dict[str, Any]) -> Dict[str, str]:
        """Build metadata dictionary from file information.
        
        Args:
            file_info: File information from WebDAV
            
        Returns:
            Metadata dictionary
        """
        metadata = {}
        
        # Add basic file properties
        if 'content_type' in file_info:
            metadata['content_type'] = str(file_info['content_type'])
        
        if 'size' in file_info:
            metadata['file_size'] = str(file_info['size'])
            
        if 'owner' in file_info:
            metadata['owner'] = str(file_info['owner'])
            
        if 'permissions' in file_info:
            metadata['permissions'] = str(file_info['permissions'])
            
        if 'etag' in file_info:
            metadata['etag'] = str(file_info['etag'])
            
        # Add path information
        metadata['file_path'] = str(file_info.get('path', ''))
        metadata['server_url'] = str(self.server_url)
        
        return metadata

    def _is_supported_file(self, file_info: Dict[str, Any]) -> bool:
        """Check if the file type is supported for indexing.
        
        Args:
            file_info: File information dictionary
            
        Returns:
            True if file should be indexed, False otherwise
        """
        file_path = file_info.get('path', '')
        
        # Check file extension using instance-specific extensions
        if not is_accepted_file_ext(file_path, self.file_extensions):
            logger.debug(f"Unsupported extension for: {file_path}")
            logger.debug(f"Supported extensions: {sorted(list(self.file_extensions))[:10]}...")
            return False
        
        # Skip very large files (over 50MB by default)
        file_size = file_info.get('size', 0)
        max_file_size = 50 * 1024 * 1024  # 50MB
        if file_size > max_file_size:
            logger.debug(f"Skipping large file {file_path} ({file_size} bytes > {max_file_size})")
            return False
        
        return True

    def validate_connector_settings(self) -> None:
        """Validate that the connector configuration is correct."""
        # Check required credentials
        if not all([self.server_url, self.username, self.password]):
            raise ConnectorMissingCredentialError(
                "Nextcloud connector requires server_url, username, and password"
            )
        
        # Validate server URL format
        if not (self.server_url.startswith('http://') or self.server_url.startswith('https://')):
            raise ValueError("Server URL must start with http:// or https://")
        
        # Test connection
        try:
            if not self.client.test_connection():
                raise ConnectionError(
                    f"Failed to connect to Nextcloud server at {self.server_url}. "
                    "Please check your credentials and server URL."
                )
            logger.info(f"✓ Successfully connected to Nextcloud at {self.server_url}")
        except Exception as e:
            raise ConnectionError(
                f"Connection test failed: {e}. Please verify your Nextcloud "
                "server URL, username, and password/app token."
            )

    def validate_credentials(self) -> bool:
        """Validate credentials by testing connection."""
        try:
            self.validate_connector_settings()
            return True
        except Exception:
            return False


# Development testing
if __name__ == "__main__":
    import os
    
    # Test the connector
    connector = NextcloudConnector()
    connector.load_credentials({
        "server_url": os.environ.get("NEXTCLOUD_SERVER_URL", "https://your-nextcloud.com"),
        "username": os.environ.get("NEXTCLOUD_USERNAME", "your-username"),
        "password": os.environ.get("NEXTCLOUD_PASSWORD", "your-password"),
    })
    
    # Test connection
    logger.info("Testing connection...")
    try:
        connector.validate_connector_settings()
        logger.info("Connection successful")
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        exit(1)
    
    # Load some documents
    logger.info("Loading documents...")
    document_batches = connector.load_from_state()
    first_batch = next(document_batches, [])
    
    logger.info(f"Found {len(first_batch)} documents in first batch")
    for doc in first_batch[:3]:  # Show first 3 documents
        logger.info(f"- {doc.semantic_identifier} (ID: {doc.id})")
        logger.info(f"  Updated: {doc.doc_updated_at}")
        logger.info(f"  Text preview: {doc.sections[0].text[:100]}...")
        logger.info("")
