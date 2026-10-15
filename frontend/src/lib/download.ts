import { ApiError, type DownloadFile } from '../api/client'

/** 只使用已完成的本地 Blob；延迟释放 URL，给浏览器读取文件的时间。 */
export function saveDownload(file: DownloadFile) {
  let url: string | undefined
  const anchor = document.createElement('a')
  try {
    url = URL.createObjectURL(file.blob)
    anchor.href = url
    anchor.download = file.filename
    anchor.hidden = true
    document.body.append(anchor)
    anchor.click()
  } catch {
    if (url) URL.revokeObjectURL(url)
    throw new ApiError(0, 'DOWNLOAD_SAVE_FAILED', '无法启动文件保存，请检查浏览器下载设置')
  } finally {
    anchor.remove()
  }
  const objectUrl = url
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
}
