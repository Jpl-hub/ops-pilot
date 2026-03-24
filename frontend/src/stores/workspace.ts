import { defineStore } from 'pinia'

import { get, post, type UserRole } from '@/lib/api'

export type WorkspaceMessage =
  | { id: string; role: 'assistant'; kind: 'welcome'; title: string; lines: string[] }
  | { id: string; role: 'user'; kind: 'query'; text: string; company: string }
  | { id: string; role: 'assistant'; kind: 'result'; payload: any }

type WorkspaceOverview = {
  companies: string[]
  task_queue: any[]
  task_summary: Record<string, number>
  alert_queue: any[]
  alert_workflow_summary: Record<string, number>
  alert_summary: {
    total_alerts: number
    active_companies: number
    preferred_period: string
  } | null
  execution_bus_records?: {
    total: number
    records: any[]
  } | null
  workspace_history?: {
    total: number
    records: any[]
  } | null
}

type CompanyWorkspace = {
  company_name: string
  report_period: string
  intelligence_runtime?: {
    runtime_bus?: {
      total: number
      records: any[]
    }
  } | null
  runtime_capsule?: {
    summary?: {
      active_modules: number
      latest_label?: string | null
    }
    modules: any[]
  } | null
}

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    selectedCompany: '',
    query: '',
    companies: [] as string[],
    messages: [] as WorkspaceMessage[],
    latestPayload: null as any,
    overview: null as WorkspaceOverview | null,
    companyWorkspace: null as CompanyWorkspace | null,
    loadingOverview: false,
    loadingCompanyWorkspace: false,
    loadingTurn: false,
    overviewError: '' as string | null,
    companyWorkspaceError: '' as string | null,
    turnError: '' as string | null,
  }),
  getters: {
    taskQueue: (state) => state.overview?.task_queue || [],
    taskSummary: (state) => state.overview?.task_summary || null,
    alertQueue: (state) => state.overview?.alert_queue || [],
    alertWorkflowSummary: (state) => state.overview?.alert_workflow_summary || null,
    overviewSummary: (state) => state.overview?.alert_summary || null,
    executionBus: (state) => state.overview?.execution_bus_records?.records || [],
    workspaceHistory: (state) => state.overview?.workspace_history?.records || [],
    companyRuntimeCapsule: (state) => state.companyWorkspace?.runtime_capsule || null,
    companyRuntimeBus: (state) => state.companyWorkspace?.intelligence_runtime?.runtime_bus?.records || [],
    followUps: (state) => state.latestPayload?.follow_up_questions || [],
    agentFlow: (state) => state.latestPayload?.agent_flow || [],
    controlPlane: (state) => state.latestPayload?.control_plane || null,
    insightCards: (state) => state.latestPayload?.insight_cards || [],
    evidenceGroups: (state) => state.latestPayload?.evidence_groups || [],
    charts: (state) => state.latestPayload?.charts || [],
    formulas: (state) => state.latestPayload?.formula_cards || [],
  },
  actions: {
    resetConversation(title: string, label: string) {
      this.messages = [
        {
          id: 'welcome',
          role: 'assistant',
          kind: 'welcome',
          title,
          lines: [`${label}模式已就绪。`],
        },
      ]
      this.latestPayload = null
      this.companyWorkspace = null
      this.turnError = null
    },
    async loadOverview(role: UserRole) {
      this.loadingOverview = true
      this.overviewError = null
      try {
        const payload = await get<WorkspaceOverview>(
          `/workspace/overview?user_role=${encodeURIComponent(role)}`,
        )
        this.overview = payload
        this.companies = payload.companies || []
        if (!this.companies.includes(this.selectedCompany)) {
          this.selectedCompany = this.companies[0] || ''
        }
        if (this.selectedCompany) {
          await this.loadCompanyWorkspace(role)
        }
      } catch (error) {
        this.overviewError = error instanceof Error ? error.message : '工作台加载失败'
      } finally {
        this.loadingOverview = false
      }
    },
    async loadCompanyWorkspace(role: UserRole) {
      if (!this.selectedCompany) {
        this.companyWorkspace = null
        return
      }
      this.loadingCompanyWorkspace = true
      this.companyWorkspaceError = null
      try {
        this.companyWorkspace = await get<CompanyWorkspace>(
          `/company/workspace?company_name=${encodeURIComponent(this.selectedCompany)}&user_role=${encodeURIComponent(role)}`,
        )
      } catch (error) {
        this.companyWorkspaceError =
          error instanceof Error ? error.message : '公司运行态加载失败'
      } finally {
        this.loadingCompanyWorkspace = false
      }
    },
    async sendQuery(role: UserRole, inputQuery?: string) {
      const actualQuery = (inputQuery || this.query).trim()
      if (!actualQuery || !this.selectedCompany) return

      this.turnError = null
      this.loadingTurn = true
      this.messages.push({
        id: `user-${Date.now()}`,
        role: 'user',
        kind: 'query',
        text: actualQuery,
        company: this.selectedCompany,
      })
      this.query = ''

      try {
        const payload = await post('/chat/turn', {
          query: actualQuery,
          company_name: this.selectedCompany,
          user_role: role,
        })
        this.latestPayload = payload
        this.messages.push({
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          kind: 'result',
          payload,
        })
        await this.loadCompanyWorkspace(role)
      } catch (error) {
        this.turnError = error instanceof Error ? error.message : '分析执行失败'
      } finally {
        this.loadingTurn = false
      }
    },
    async updateTaskStatus(
      taskId: string,
      status: 'queued' | 'in_progress' | 'done' | 'blocked',
      role: UserRole,
      note?: string,
    ) {
      await post('/tasks/update', {
        task_id: taskId,
        status,
        user_role: role,
        report_period: this.overview?.alert_summary?.preferred_period,
        note,
      })
      await this.loadOverview(role)
      await this.loadCompanyWorkspace(role)
    },
    async updateAlertStatus(
      alertId: string,
      status: 'new' | 'dispatched' | 'in_progress' | 'resolved' | 'dismissed',
      note?: string,
    ) {
      await post('/alerts/update', {
        alert_id: alertId,
        status,
        report_period: this.overview?.alert_summary?.preferred_period,
        note,
      })
      await this.loadOverview('management')
      await this.loadCompanyWorkspace('management')
    },
    async dispatchAlertToTask(alertId: string, role: UserRole, note?: string) {
      await post('/alerts/dispatch', {
        alert_id: alertId,
        user_role: role,
        report_period: this.overview?.alert_summary?.preferred_period,
        note,
      })
      await this.loadOverview(role)
      await this.loadCompanyWorkspace(role)
    },
  },
})
