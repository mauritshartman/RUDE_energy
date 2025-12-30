<script setup>
import Menu from './components/Menu.vue';
import { darkTheme } from 'naive-ui';

</script>

<template>
  <n-config-provider :theme="darkTheme">
    <n-global-style />
    <div style="margin-left: 20px; margin-right: 20px;">
      <Menu></Menu>

      <RouterView />
    </div>
  </n-config-provider>
</template>

<style scoped>
</style>
