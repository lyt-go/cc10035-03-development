import { createRouter, createWebHistory } from 'vue-router'

import GatewayRedelivery from '@/views/GatewayRedelivery.vue'
import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 静态路由优先于 /:moduleKey 动态路由匹配
    { path: '/gateway_redelivery', name: 'gateway-redelivery', component: GatewayRedelivery },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
