<script setup>
import { NH4, NTable, NProgress } from "naive-ui";
import { useControlStore } from "../stores/control";

const control = useControlStore();
</script>

<template>
  <template v-if="control.active_inv_control">
    <n-h4 prefix="bar"> Manual Control Status </n-h4>

    <n-table :bordered="false" :single-line="false">
      <thead>
        <tr>
          <th></th>
          <th>L1</th>
          <th>L2</th>
          <th>L3</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>PBapp</td>
          <td>{{ control.active_inv_control?.L1.PBapp }} W</td>
          <td>{{ control.active_inv_control?.L2.PBapp }} W</td>
          <td>{{ control.active_inv_control?.L3?.PBapp }} W</td>
        </tr>
        <tr>
          <td>PBnow</td>
          <td>{{ control.active_inv_control?.L1.PBnow }} W</td>
          <td>{{ control.active_inv_control?.L2.PBnow }} W</td>
          <td>{{ control.active_inv_control?.L3?.PBnow }} W</td>
        </tr>
        <tr>
          <td>PGnow</td>
          <td>{{ control.active_inv_control?.L1.PGnow }} W</td>
          <td>{{ control.active_inv_control?.L2.PGnow }} W</td>
          <td>{{ control.active_inv_control?.L3?.PGnow }} W</td>
        </tr>
        <tr>
          <td>VGnow</td>
          <td>{{ control.active_inv_control?.L1.VGnow }} W</td>
          <td>{{ control.active_inv_control?.L2.VGnow }} W</td>
          <td>{{ control.active_inv_control?.L3?.VGnow }} W</td>
        </tr>
        <tr>
          <td>Imax</td>
          <td>{{ control.active_inv_control?.L1.Imax }} W</td>
          <td>{{ control.active_inv_control?.L2.Imax }} W</td>
          <td>{{ control.active_inv_control?.L3?.Imax }} W</td>
        </tr>
        <tr>
          <td>PGmax</td>
          <td>{{ control.active_inv_control?.L1.PGmax }} W</td>
          <td>{{ control.active_inv_control?.L2.PGmax }} W</td>
          <td>{{ control.active_inv_control?.L3?.PGmax }} W</td>
        </tr>
        <tr>
          <td>PGmin</td>
          <td>{{ control.active_inv_control?.L1.PGmin }} W</td>
          <td>{{ control.active_inv_control?.L2.PGmin }} W</td>
          <td>{{ control.active_inv_control?.L3?.PGmin }} W</td>
        </tr>
        <tr>
          <td>Pother</td>
          <td>{{ control.active_inv_control?.L1.Pother }} W</td>
          <td>{{ control.active_inv_control?.L2.Pother }} W</td>
          <td>{{ control.active_inv_control?.L3?.Pother }} W</td>
        </tr>
        <tr>
          <td>PBlim_min</td>
          <td>{{ control.active_inv_control?.L1.PBlim_min }} W</td>
          <td>{{ control.active_inv_control?.L2.PBlim_min }} W</td>
          <td>{{ control.active_inv_control?.L3?.PBlim_min }} W</td>
        </tr>
        <tr>
          <td>PBlim_max</td>
          <td>{{ control.active_inv_control?.L1.PBlim_max }} W</td>
          <td>{{ control.active_inv_control?.L2.PBlim_max }} W</td>
          <td>{{ control.active_inv_control?.L3?.PBlim_max }} W</td>
        </tr>
        <tr>
          <td>PBsent</td>
          <td>{{ control.active_inv_control?.L1.PBsent }} W</td>
          <td>{{ control.active_inv_control?.L2.PBsent }} W</td>
          <td>{{ control.active_inv_control?.L3?.PBsent }} W</td>
        </tr>
      </tbody>
    </n-table>
  </template>

  <n-h4 prefix="bar"> Inverter Status </n-h4>
  <template v-if="control.active_stats">
    <n-table :bordered="false" :single-line="false">
      <thead>
        <tr>
          <th colspan="2">Inverter</th>
          <th>Current</th>
          <th>Voltage</th>
          <th>Power</th>
          <th>Status</th>
          <th>Charge</th>
          <th>Temperature</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="(inv, inv_name) in control.active_stats.inverters">
          <tr>
            <td rowspan="2">
              {{ inv_name }}<br /><em>(connected to {{ inv.phase }})</em>
            </td>
            <td>Battery</td>
            <td>{{ inv.battery.A }} A</td>
            <td>{{ inv.battery.V }} V</td>
            <td></td>
            <td>{{ inv.battery.status }}</td>
            <td>
              <n-progress
                type="line"
                :percentage="Math.round(inv.battery.charge)"
              />
            </td>
            <td>
              {{ inv.battery.temp_l }} &#8451; -
              {{ inv.battery.temp_l }} &#8451;
            </td>
          </tr>
          <tr>
            <td>AC side</td>
            <td>{{ inv.ac_side.A }} A</td>
            <td>{{ inv.ac_side.V }} V</td>
            <td>{{ inv.ac_side.P }} W</td>
            <td colspan="3"></td>
          </tr>
        </template>
      </tbody>
    </n-table>
  </template>
  <p v-else>Inverter status unavailable</p>

  <n-h4 prefix="bar"> Data Manager Status </n-h4>
  <template v-if="control.active_stats">
    <n-table :bordered="false" :single-line="false">
      <thead>
        <tr>
          <th></th>
          <th>L1</th>
          <th>L2</th>
          <th>L3</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Current</td>
          <td>{{ control.active_stats.data_manager.L1.A }} A</td>
          <td>{{ control.active_stats.data_manager.L2.A }} A</td>
          <td>{{ control.active_stats.data_manager.L3.A }} A</td>
        </tr>
        <tr>
          <td>Max Current</td>
          <td>{{ control.active_stats.data_manager.L1.Amax }} A</td>
          <td>{{ control.active_stats.data_manager.L2.Amax }} A</td>
          <td>{{ control.active_stats.data_manager.L3.Amax }} A</td>
        </tr>
        <tr>
          <td>Voltage</td>
          <td>{{ control.active_stats.data_manager.L1.V }} V</td>
          <td>{{ control.active_stats.data_manager.L2.V }} V</td>
          <td>{{ control.active_stats.data_manager.L3.V }} V</td>
        </tr>
        <tr>
          <td>Power</td>
          <td>{{ control.active_stats.data_manager.L1.P }} W</td>
          <td>{{ control.active_stats.data_manager.L2.P }} W</td>
          <td>{{ control.active_stats.data_manager.L3.P }} W</td>
        </tr>
        <tr>
          <td>Status</td>
          <td>{{ control.active_stats.data_manager.L1.status }}</td>
          <td>{{ control.active_stats.data_manager.L2.status }}</td>
          <td>{{ control.active_stats.data_manager.L3.status }}</td>
        </tr>
      </tbody>
    </n-table>
  </template>
  <p v-else>Data Manager status unavailable</p>
</template>
