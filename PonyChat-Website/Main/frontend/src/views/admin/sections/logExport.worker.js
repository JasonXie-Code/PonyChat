self.onmessage = ({ data: { value, download } }) => {
  try {
    const text = typeof value === 'string' && !download ? value : JSON.stringify(value ?? null, null, 2)
    self.postMessage({ result: download ? new Blob([text], { type: 'application/json' }) : text })
  } catch (error) {
    self.postMessage({ error: error.message })
  }
}
