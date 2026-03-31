import { defineStore } from 'pinia'

import { get, post, type UserRole } from '@/lib/api'

export type WorkspaceMessage =
  | { id: string; role: 'assistant'; kind: 'welcome'; title: string; lines: string[] }
  | { id: string; role: 'user'; kind: 'query'; text: string; company: string }
  | { id: string; role: 'assistant'; kind: 'result'; payload: any }

type WorkspaceOverview = {
  companies: string[]
  role_profile?: {
    label?: string
    focus_title?: string
    starter_queries?: string[]
  } | null
  watchboard?: {
    summary: {
      tracked_companies: number
      companies_with_new_alerts: number
      companies_in_progress: number
    }
    items: any[]
  } | null
  task_queue: any[]
  task_summary: Record<string, number>
  alert_queue: any[]
  alert_workflow_summary: Record<string, number>
  execution_bus_summary?: {
    tasks?: Record<string, number>
    alerts?: Record<string, number>
    watchboard?: Record<string, number>
    history?: Record<string, number>
  } | null
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

type WorkspaceCompaniesPayload = {
  companies: string[]
  preferred_period?: string
  available_periods?: string[]
}

type CompanyWorkspace = {
  company_name: string
  report_period: string
  score_summary?: {
    total_score: number
    grade: string
    subindustry?: string
    subindustry_percentile?: number
    risk_count: number
    opportunity_count: number
  } | null
  top_risks?: string[]
  top_opportunities?: string[]
  action_cards?: any[]
  alerts?: {
    summary: Record<string, number>
    items: any[]
  } | null
  tasks?: {
    summary: Record<string, number>
    items: any[]
  } | null
  watchboard?: {
    tracked: boolean
    note?: string | null
    new_alerts?: number
    in_progress_alerts?: number
    task_count?: number
  } | null
  research?: {
    status: string
    report_title?: string
    institution?: string
    claim_matches?: number
    claim_mismatches?: number
    forecast_count?: number
    detail?: string
  } | null
  timeline?: {
    latest_period?: string
    key_numbers?: any[]
    snapshots: any[]
  } | null
  recent_runs?: {
    total?: number
    items?: any[]
  } | null
  execution_stream?: {
    total?: number
    records?: any[]
  } | null
  intelligence_runtime?: {
    summary?: {
      active_modules: number
      latest_label?: string | null
      latest_created_at?: string | null
      run_count?: number
    }
    module_pulses?: any[]
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
    loadingCompanies: false,
    loadingOverview: false,
    loadingCompanyWorkspace: false,
    loadingTurn: false,
    companiesError: '' as string | null,
    overviewError: '' as string | null,
    companyWorkspaceError: '' as string | null,
    turnError: '' as string | null,
  }),
  getters: {
    watchboardSummary: (state) => state.overview?.watchboard?.summary || null,
    watchboardItems: (state) => state.overview?.watchboard?.items || [],
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
    syncCompanies(companies: string[]) {
      const unique = companies.filter(
        (company, index) => !!company && companies.indexOf(company) === index,
      )
      if (unique.length) {
        this.companies = unique
        if (!unique.includes(this.selectedCompany)) {
          this.selectedCompany = unique[0]
        }
        return
      }
      this.companies = []
      this.selectedCompany = ''
    },
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
      this.overview = null
      this.companyWorkspace = null
      this.companiesError = null
      this.overviewError = null
      this.companyWorkspaceError = null
      this.turnError = null
    },
    async loadCompanies() {
      this.loadingCompanies = true
      this.companiesError = null
      try {
        const payload = await get<WorkspaceCompaniesPayload>('/workspace/companies')
        this.syncCompanies(payload.companies || [])
      } catch (error) {
        this.companiesError = error instanceof Error ? error.message : '公司池加载失败'
        throw error
      } finally {
        this.loadingCompanies = false
      }
    },
    async loadOverview(role: UserRole) {
      this.loadingOverview = true
      this.overviewError = null
      try {
        const payload = await get<WorkspaceOverview>(
          `/workspace/overview?user_role=${encodeURIComponent(role)}`,
        )
        this.overview = payload
        this.syncCompanies(payload.companies || [])
      } catch (error) {
        this.overviewError = error instanceof Error ? error.message : '工作台加载失败'
      } finally {
        this.loadingOverview = false
      }
    },
    async bootstrap(role: UserRole) {
      await this.loadCompanies()
      if (this.selectedCompany) {
        await this.loadCompanyWorkspace(role)
      }
      await this.loadOverview(role)
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
    async addCurrentCompanyToWatchboard(role: UserRole, note?: string) {
      if (!this.selectedCompany) return
      await post('/watchboard/add', {
        company_name: this.selectedCompany,
        user_role: role,
        report_period: this.overview?.alert_summary?.preferred_period,
        note,
      })
      await this.loadOverview(role)
      await this.loadCompanyWorkspace(role)
    },
    async removeCurrentCompanyFromWatchboard(role: UserRole) {
      if (!this.selectedCompany) return
      await post('/watchboard/remove', {
        company_name: this.selectedCompany,
        user_role: role,
        report_period: this.overview?.alert_summary?.preferred_period,
      })
      await this.loadOverview(role)
      await this.loadCompanyWorkspace(role)
    },
    async scanWatchboard(role: UserRole) {
      await post('/watchboard/scan', {
        user_role: role,
        report_period: this.overview?.alert_summary?.preferred_period,
      })
      await this.loadOverview(role)
      await this.loadCompanyWorkspace(role)
    },
    async dispatchWatchboard(role: UserRole, limit = 10) {
      await post('/watchboard/dispatch', {
        user_role: role,
        report_period: this.overview?.alert_summary?.preferred_period,
        limit,
      })
      await this.loadOverview(role)
      await this.loadCompanyWorkspace(role)
    },
  },
})
