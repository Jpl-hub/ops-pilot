import { ref } from 'vue'

export function useAsyncState<T>() {
  const data = ref<T | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function execute(loader: () => Promise<T>) {
    loading.value = true
    error.value = null
    try {
      data.value = await loader()
      return data.value
    } catch (err) {
      error.value = err instanceof Error ? err.message : '请求失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, execute }
}
