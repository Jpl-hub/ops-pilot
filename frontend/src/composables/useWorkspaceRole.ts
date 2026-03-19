import { computed } from 'vue'

import type { UserRole } from '@/lib/api'

const ROLE_COPY: Record<
  UserRole,
  {
    label: string
    title: string
    fallbackQueries: string[]
  }
> = {
  investor: {
    label: '投资者',
    title: '围绕收益质量展开分析',
    fallbackQueries: [
      '这家公司当前最值得警惕的风险是什么？',
      '把这家公司和同业头部公司做一下对比。',
      '最新研报和真实财报有没有偏差？',
    ],
  },
  management: {
    label: '企业管理者',
    title: '围绕经营动作展开分析',
    fallbackQueries: [
      '给我一份当前经营体检和整改优先级。',
      '现金、应收和库存哪个环节最拖后腿？',
      '当前最先要修复的经营问题是什么？',
    ],
  },
  regulator: {
    label: '监管 / 风控角色',
    title: '围绕风险巡检展开分析',
    fallbackQueries: [
      '当前主周期哪些公司风险抬升最快？',
      '这家公司有哪些需要重点跟踪的事件信号？',
      '这家公司和研报观点有明显偏差吗？',
    ],
  },
}

export function useWorkspaceRole(role: () => UserRole) {
  const roleCopy = computed(() => ROLE_COPY[role()] || ROLE_COPY.investor)
  return { roleCopy }
}
