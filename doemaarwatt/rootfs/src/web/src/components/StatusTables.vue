<script setup>
import { NH4, NTable, NProgress, NCollapse, NCollapseItem } from "naive-ui";
import { useControlStore } from "../stores/control";

const control = useControlStore();

// Format a power value in watts as kW with one decimal; null/undefined -> em dash.
function fmtKW(watts) {
  if (watts === null || watts === undefined) return "—";
  return `${Math.round(watts / 100) / 10} kW`;
}

// Round a value for display, tolerating null/undefined.
function r(v) {
  return v === null || v === undefined ? "—" : Math.round(v);
}
</script>

<template>
  <template v-if="control.battery_rows.length">
    <n-collapse arrow-placement="right">
      <n-collapse-item>
        <template #header>
          <n-h4 prefix="bar"> Battery Inverters </n-h4>
        </template>
        <n-table :bordered="false" :single-line="false">
          <thead>
            <tr>
              <th>Inverter</th>
              <th>Phase</th>
              <th>&nbsp;</th>
              <th>Current</th>
              <th>Voltage</th>
              <th>Power</th>
              <th>Status</th>
              <th>Charge</th>
              <th>Temperature</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="inv in control.battery_rows" :key="inv.name">
              <tr>
                <td rowspan="2">{{ inv.name }}</td>
                <td rowspan="2">{{ inv.phase }}</td>
                <td>Battery</td>
                <td>{{ r(inv.battery.A) }} A</td>
                <td>{{ r(inv.battery.V) }} V</td>
                <td></td>
                <td>{{ inv.battery.status }}</td>
                <td>
                  <n-progress
                    type="line"
                    :percentage="Math.round(inv.battery.charge ?? 0)"
                  />
                </td>
                <td>
                  {{ r(inv.battery.temp_l) }} &#8451; -
                  {{ r(inv.battery.temp_h) }} &#8451;
                </td>
              </tr>
              <tr>
                <td>AC side</td>
                <td>{{ r(inv.ac?.A) }} A</td>
                <td>{{ r(inv.ac?.V) }} V</td>
                <td>{{ r(inv.ac?.P) }} W</td>
                <td colspan="3"></td>
              </tr>
            </template>
          </tbody>
        </n-table>
      </n-collapse-item>
    </n-collapse>
  </template>

  <template v-if="control.solar_rows.length">
    <n-collapse arrow-placement="right">
      <n-collapse-item>
        <template #header>
          <n-h4 prefix="bar"> Solar Inverters </n-h4>
        </template>

        <n-table
          v-for="sol in control.solar_rows"
          :key="sol.name"
          :bordered="false"
          :single-line="false"
        >
          <thead>
            <tr>
              <th>{{ sol.name }}</th>
              <th>L1</th>
              <th>L2</th>
              <th>L3</th>
              <th>Total</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Power</td>
              <td>{{ fmtKW(sol.ac_side?.L1?.P) }}</td>
              <td>{{ fmtKW(sol.ac_side?.L2?.P) }}</td>
              <td>{{ fmtKW(sol.ac_side?.L3?.P) }}</td>
              <td>{{ fmtKW(sol.total_power) }}</td>
            </tr>
            <tr>
              <td>Setpoint Limit</td>
              <td colspan="4">
                {{ sol.setpoint_limit === null || sol.setpoint_limit === undefined ? "not set" : fmtKW(sol.setpoint_limit) }}
              </td>
            </tr>
          </tbody>
        </n-table>
      </n-collapse-item>
    </n-collapse>
  </template>

  <template v-if="control.energy_meter">
    <n-collapse arrow-placement="right">
      <n-collapse-item>
        <template #header>
          <n-h4 prefix="bar"> Energy Meter </n-h4>
        </template>

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
              <td>{{ r(control.energy_meter.L1.A) }} A</td>
              <td>{{ r(control.energy_meter.L2.A) }} A</td>
              <td>{{ r(control.energy_meter.L3.A) }} A</td>
            </tr>
            <tr>
              <td>Max Current</td>
              <td>{{ r(control.energy_meter.L1.Amax) }} A</td>
              <td>{{ r(control.energy_meter.L2.Amax) }} A</td>
              <td>{{ r(control.energy_meter.L3.Amax) }} A</td>
            </tr>
            <tr>
              <td>Voltage</td>
              <td>{{ r(control.energy_meter.L1.V) }} V</td>
              <td>{{ r(control.energy_meter.L2.V) }} V</td>
              <td>{{ r(control.energy_meter.L3.V) }} V</td>
            </tr>
            <tr>
              <td>Power</td>
              <td>{{ r(control.energy_meter.L1.P) }} W</td>
              <td>{{ r(control.energy_meter.L2.P) }} W</td>
              <td>{{ r(control.energy_meter.L3.P) }} W</td>
            </tr>
            <tr>
              <td>Status</td>
              <td>{{ control.energy_meter.L1.status }}</td>
              <td>{{ control.energy_meter.L2.status }}</td>
              <td>{{ control.energy_meter.L3.status }}</td>
            </tr>
          </tbody>
        </n-table>
      </n-collapse-item>
    </n-collapse>
  </template>
</template>
