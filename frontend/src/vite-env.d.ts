/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 二维码与邀请链接使用的对外地址，例如 https://score.example.com；未设置时使用当前站点。 */
  readonly VITE_PUBLIC_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
