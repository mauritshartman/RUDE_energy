<script setup>
import Menu from './components/Menu.vue';
import { darkTheme } from 'naive-ui';

</script>

<template>
  <n-config-provider :theme="darkTheme">
    <div style="margin-left: 20px; margin-right: 20px; margin-top: 5px;">
      <Menu></Menu>

      <RouterView />
    </div>

    <n-global-style />
  </n-config-provider>
</template>
