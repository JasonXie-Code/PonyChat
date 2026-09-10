import { createRouter, createWebHistory } from 'vue-router'
import { useAdminStore } from '../stores/adminStore'

const HomeView = () => import('../views/HomeView.vue')
const DetailView = () => import('../views/DetailView.vue')
const ArchiveView = () => import('../views/ArchiveView.vue')
const CharacterHallView = () => import('../views/CharacterHallView.vue')
const MbtiChoiceView = () => import('../views/MbtiChoiceView.vue')
const DataExportView = () => import('../views/DataExportView.vue')
const DriveView = () => import('../views/DriveView.vue')
const WebChatView = () => import('../views/WebChatView.vue')
const AdminLoginView = () => import('../views/admin/AdminLoginView.vue')
const AdminLayout = () => import('../views/admin/AdminLayout.vue')
const TerminalView = () => import('../views/admin/TerminalView.vue')
const OverviewSection = () => import('../views/admin/sections/OverviewSection.vue')
const UsersSection = () => import('../views/admin/sections/UsersSection.vue')
const CharactersSection = () => import('../views/admin/sections/CharactersSection.vue')
const AssetsSection = () => import('../views/admin/sections/AssetsSection.vue')
const ConversationsSection = () => import('../views/admin/sections/ConversationsSection.vue')
const RecoverySection = () => import('../views/admin/sections/RecoverySection.vue')
const InvitesSection = () => import('../views/admin/sections/InvitesSection.vue')
const ModelsSection = () => import('../views/admin/sections/ModelsSection.vue')
const SystemSection = () => import('../views/admin/sections/SystemSection.vue')
const ConversationLogsSection = () => import('../views/admin/sections/ConversationLogsSection.vue')

const isDriveHost = typeof window !== 'undefined' && window.location.hostname === 'drive.ponychat.org'
const driveDevRoutes = import.meta.env.DEV
  ? [
      {
        path: '/drive',
        name: 'drive-dev',
        component: DriveView,
        meta: {
          title: 'PonyChat Drive',
          description: 'PonyChat 私人网盘。',
        },
      },
    ]
  : []

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: isDriveHost ? DriveView : HomeView,
      meta: {
        title: isDriveHost ? 'PonyChat Drive' : 'PonyChat — AI companionship',
        description: isDriveHost
          ? 'PonyChat 私人网盘。'
          : 'PonyChat: character conversations, lasting memories and voice companionship.',
      },
    },
    ...driveDevRoutes,
    {
      path: '/character-hall',
      name: 'character-hall',
      component: CharacterHallView,
      meta: {
        title: 'PonyChat — 认证角色大厅',
        description: '浏览 PonyChat 大厅中已经发布的认证角色：头像、签名、MBTI、人气数据和角色档案。',
      },
    },
    {
      path: '/mbti',
      name: 'mbti-choice',
      component: MbtiChoiceView,
      meta: {
        title: 'PonyChat — 选择 MBTI 测验类型',
        description:
          '在标准人格类型测验与小马情境 MLP MBTI 测验之间选择；均为浏览器本地作答的娱乐或自测用途。',
      },
    },
    {
      path: '/detail',
      name: 'detail',
      component: DetailView,
      meta: {
        title: 'PonyChat — 了解产品与进展',
        description:
          '介绍 PonyChat 现在能做什么、可以怎么玩，以及后续推进方向；完整体验以 Android 客户端为主。',
      },
    },
    {
      path: '/archive',
      name: 'archive',
      component: ArchiveView,
      meta: {
        title: 'PonyChat — 项目近况（2026-09-06）',
        description: 'PonyChat 近期开发进展：普通聊天、语音消息、角色主页、Voice Lab 与部署近况。',
      },
    },
    {
      path: '/app',
      name: 'chat-app',
      component: WebChatView,
      meta: {
        title: 'PonyChat — 网页聊天',
        description: '轻量网页版对话（角色由管理后台配置）。',
      },
    },
    {
      path: '/data-export',
      name: 'data-export',
      component: DataExportView,
      meta: {
        title: 'PonyChat — 个人数据导出',
        description: '登录 PonyChat 账号，按角色和模式导出自己的聊天记录 TXT 文本。',
      },
    },
    {
      path: '/database',
      name: 'mlp-database',
      component: () => import('../views/DatabaseView.vue'),
      meta: {
        title: 'PonyChat — 小马世界资料库',
        description: 'PonyChat 小马世界资料库查询。',
      },
    },
    {
      path: '/admin/login',
      name: 'admin-login',
      component: AdminLoginView,
      meta: {
        title: 'PonyChat — 管理登录',
        description: 'PonyChat 管理后台登录。',
      },
    },
    {
      path: '/admin',
      component: AdminLayout,
      meta: { requiresAdmin: true },
      children: [
        { path: '', redirect: '/admin/overview' },
        {
          path: 'terminal',
          name: 'admin-terminal',
          component: TerminalView,
          meta: { title: 'PonyChat — 后端控制台', description: 'PonyChat 后端实时日志与内置管理命令。' },
        },
        {
          path: 'overview',
          name: 'admin-overview',
          component: OverviewSection,
          meta: { title: 'PonyChat — 数据概览' },
        },
        {
          path: 'users',
          name: 'admin-users',
          component: UsersSection,
          meta: { title: 'PonyChat — 用户管理' },
        },
        {
          path: 'characters',
          name: 'admin-characters',
          component: CharactersSection,
          meta: { title: 'PonyChat — 角色管理' },
        },
        {
          path: 'web-chars',
          redirect: '/admin/characters',
        },
        {
          path: 'assets',
          name: 'admin-assets',
          component: AssetsSection,
          meta: { title: 'PonyChat — 素材管理', description: 'PonyChat 素材库管理。' },
        },
        {
          path: 'conversations',
          name: 'admin-conversations',
          component: ConversationsSection,
          meta: { title: 'PonyChat — 对话记录' },
        },
        {
          path: 'recovery',
          name: 'admin-recovery',
          component: RecoverySection,
          meta: { title: 'PonyChat — 数据恢复' },
        },
        {
          path: 'invites',
          name: 'admin-invites',
          component: InvitesSection,
          meta: { title: 'PonyChat — 邀请码' },
        },
        {
          path: 'models',
          name: 'admin-models',
          component: ModelsSection,
          meta: { title: 'PonyChat — 模型配置' },
        },
        {
          path: 'system',
          name: 'admin-system',
          component: SystemSection,
          meta: { title: 'PonyChat — 系统设置' },
        },
        {
          path: 'conversation-logs',
          name: 'admin-conversation-logs',
          component: ConversationLogsSection,
          meta: { title: 'PonyChat — 对话日志', description: 'PonyChat 大模型调用日志在线审计。' },
        },
      ],
    },
  ],
  scrollBehavior(to, _from, saved) {
    if (saved) {
      return saved
    }
    if (to.hash) {
      return { el: to.hash, behavior: 'smooth', top: 0 }
    }
    return { top: 0 }
  },
})

router.beforeEach((to, _from, next) => {
  const store = useAdminStore()
  store.hydrate()
  const need = to.matched.some((r) => r.meta.requiresAdmin)
  if (need && !store.isLoggedIn) {
    next({ name: 'admin-login', query: { redirect: to.fullPath } })
    return
  }
  if (to.name === 'admin-login' && store.isLoggedIn) {
    next('/admin/overview')
    return
  }
  next()
})

export default router
