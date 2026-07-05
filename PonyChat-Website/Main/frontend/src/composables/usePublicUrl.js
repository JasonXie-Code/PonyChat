/** 拼接 public 目录资源路径，兼容 Vite `base`（如 `./`）。 */
export function usePublicUrl() {
  const base = import.meta.env.BASE_URL
  return (path) => `${base}${path.replace(/^\//, '')}`
}
