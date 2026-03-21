<script setup lang="ts">
import AppShell from '@/components/AppShell.vue'
import { useSession } from '@/lib/session'

const session = useSession()
</script>

<template>
  <AppShell title="账户与偏好" subtitle="个人中心" compact>
    <section class="mode-header">
      <div class="mode-header-copy">
        <div class="eyebrow">Profile Center</div>
        <h2 class="hero-title compact">统一管理账户、登录方式和后续订阅能力。</h2>
      </div>
    </section>

    <section class="mode-stage profile-mode-stage">
      <article class="panel mode-main-panel profile-main-panel">
        <section class="profile-overview">
          <div class="profile-avatar">{{ session.currentUser.value?.display_name?.slice(0, 1) || 'U' }}</div>
          <div class="profile-copy">
            <div class="signal-code">当前账户</div>
            <h3>{{ session.currentUser.value?.display_name }}</h3>
            <span>{{ session.currentUser.value?.username }}</span>
          </div>
        </section>

        <section class="profile-grid">
          <article class="vision-section-card">
            <div class="signal-code">账户安全</div>
            <strong>密码与登录设备</strong>
            <span>后续接入修改密码、最近登录与设备管理。</span>
          </article>
          <article class="vision-section-card">
            <div class="signal-code">订阅能力</div>
            <strong>会员与服务等级</strong>
            <span>后续接入 VIP、套餐、缴费记录和功能授权。</span>
          </article>
          <article class="vision-section-card">
            <div class="signal-code">通知偏好</div>
            <strong>预警与日报订阅</strong>
            <span>后续接入监测板提醒、日报频率和角色化推送。</span>
          </article>
        </section>
      </article>

      <aside class="mode-side-panel">
        <section class="panel side-panel-block">
          <div class="panel-header">
            <div>
              <div class="eyebrow">待建设能力</div>
              <h3>后续接入</h3>
            </div>
          </div>
          <div class="timeline-list compact-timeline">
            <div class="timeline-item">
              <strong>修改密码</strong>
              <span>统一身份能力准备接入</span>
            </div>
            <div class="timeline-item">
              <strong>套餐与缴费</strong>
              <span>订阅、账单与授权模型预留</span>
            </div>
            <div class="timeline-item">
              <strong>设备管理</strong>
              <span>最近登录、设备绑定和异常提醒</span>
            </div>
          </div>
        </section>
      </aside>
    </section>
  </AppShell>
</template>
