<template>
  <div>
    <el-menu mode="horizontal" router :default-active="$route.path" style="padding: 0 24px">
      <el-menu-item index="/">排产看板</el-menu-item>
      <el-menu-item index="/portal/debug">调试台</el-menu-item>
      <el-menu-item index="/portal/cases">案例台</el-menu-item>
      <el-menu-item index="/portal/config">配置</el-menu-item>
    </el-menu>
    <router-view v-slot="{ Component }">
      <transition name="fade" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>
  </div>
</template>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
