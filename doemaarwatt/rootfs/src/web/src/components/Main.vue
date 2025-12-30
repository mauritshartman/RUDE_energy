<script setup>
import { useControlStore } from '../stores/control';
import StatusTables from './StatusTables.vue';

const control = useControlStore()

</script>

<template>
    <h2>Main Page</h2>
    <p v-if="control.running">Currently running in mode {{ control.mode }}</p>
    <p v-else>Not running</p>

    <StatusTables />
</template>