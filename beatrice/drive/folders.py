"""Thin helpers for folders (Drive files with a folder MIME type)."""
FOLDER_MIME = 'application/vnd.google-apps.folder'

class FoldersApi:
    def __init__(self, client): self._client = client

    def children(self, folder_id, *, fields='id,name,mimeType,modifiedTime,md5Checksum,size,version'):
        if not isinstance(folder_id, str) or not folder_id:
            raise ValueError('Drive 폴더 ID가 필요합니다.')
        escaped = folder_id.replace('\\', '\\\\').replace("'", "\\'")
        return list(self._client.files.iter_files(q=f"'{escaped}' in parents and trashed=false",
                    pageSize=100, fields='nextPageToken,files(' + fields + ')'))
