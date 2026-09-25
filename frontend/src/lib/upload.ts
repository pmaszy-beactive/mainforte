import { ApiError, api } from "./api";
import { getToken } from "@/stores/auth";
import type { UploadResult } from "./types";

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

/** One multipart upload via XHR so we get progress events. */
export function uploadXhr(
  workspaceId: string,
  file: File,
  onProgress: (fraction: number) => void,
  onXhr: (xhr: XMLHttpRequest) => void,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    onXhr(xhr);
    xhr.open("POST", api.workspaces.uploadUrl(workspaceId));
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadResult);
        } catch {
          reject(new ApiError(xhr.status, "Bad upload response"));
        }
        return;
      }
      let msg = xhr.statusText;
      try {
        const d = JSON.parse(xhr.responseText) as { detail?: unknown; message?: string };
        msg = (typeof d.detail === "string" && d.detail) || d.message || msg;
      } catch {
        /* not json */
      }
      reject(new ApiError(xhr.status, msg || `HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error"));
    xhr.onabort = () => reject(new DOMException("Upload aborted", "AbortError"));
    const fd = new FormData();
    fd.append("file", file, file.name);
    xhr.send(fd);
  });
}
