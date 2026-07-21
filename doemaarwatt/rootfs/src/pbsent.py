from prettytable import PrettyTable

from common import Phase, PhasePowerMap, ProgrammingError, DMWException


def calc_PBSsent(
    phase: Phase,
    PBSapp: PhasePowerMap,
    PBSnow: PhasePowerMap,
    PGnow: float,
    VGnow: float,
    Imax: float,
) -> PhasePowerMap:
    '''Calculate safe charge/discharge amount (PBSsent) based on desired (PBSapp) amount for each inverter,
    in the current system context.

    Parameters:
    -----------
    PBSapp: PhasePowerMap
        Desired charge (negative) or discharge (positive) amount in W for each inverter
    PBSnow: PhasePowerMap
        Power at the battery inverter. Can be negative (charging the battery) or positive (discharging)
    PGnow: float
        Power at grid connection. Can be negative (drawing power from grid) or positive (supplying power)
    VGnow: float
        Measured voltage at grid connection point. Alway a positive value
    Imax: float
        Main fuse current limit at grid connection. Always a positive value

    Returns:
    --------
    PhasePowerMap
        The safe charge / discharge amount (PBSsent) that can be commanded to each inverter
    '''
    assert isinstance(PBSapp, PhasePowerMap)
    assert isinstance(PBSnow, PhasePowerMap)

    if PGnow is None or VGnow is None or Imax is None:
        raise ProgrammingError(f'missing grid measurements. PGnow: {PGnow}, VGnow: {VGnow}, Imax: {Imax}', source='calc_PBSsent')

    PGmax = abs(VGnow * Imax) # Maximum power that can safely be supplied to the grid
    PGmin = -1 * PGmax # Maximum power that can safely be drawn from the grid (negative value)
    Pother = PGnow - PBSnow.net_power  # Power consumed (negative value) or generated (positive) elsewhere in the system (eg. heat pump)
    PBSlim_min = PGmin - Pother # lower limit for net power of all controlled inverters (negative value -> consuming power)
    PBSlim_max = PGmax - Pother # upper limit for net power of all controlled inverters (positive value -> generating power)

    PBSapp_net_power = PBSapp.net_power
    PBSsent = PBSapp.copy()
    if PBSlim_min <= PBSapp_net_power and PBSapp_net_power <= PBSlim_max:
        # Combined desired power level for all inverters of this phase falls within the safe range
        return PBSsent

    if PBSapp_net_power < PBSlim_min:
        # The desired net power of all inverters would require more charging than the main grid fuse can handle
        power_exceeded = PBSlim_min - PBSapp_net_power # strictly positive

        # Solution: check for inverters in PBSapp with a negative power level (ie. charging battery inverters) and
        # check if we can be within the limit by reducing their charge level
        charging_inverters = { i: p for i, p in PBSapp.inv_power.items() if p < 0 }
        tot_charge_power = abs(sum(charging_inverters.values()))
        if power_exceeded <= tot_charge_power: # yes
            # modify PBSsent by distributing power_exceeded over the charging inverters,
            # weighted on their original PBSapp charging level
            for inv_name, inv_PBSapp in charging_inverters.items():
                power_reduction = abs(inv_PBSapp) / tot_charge_power * power_exceeded # strictly positive
                PBSsent.inv_power[inv_name] = inv_PBSapp + power_reduction

            return PBSsent

        # For now no other viable solutions. Increasing power levels on solar inverters does not guarantee that they generate
        # more power (you cannot command the sun). Also flipping a battery inverter from charging to discharging feels unsafe
        # as that battery inverter might still be charging on a different phase
        raise DMWException(f'insufficient control authority for safe PBSsent power: {PBSapp} < {PBSlim_min}', source='calc_PBSsent')

    if PBSapp_net_power > PBSlim_max:
        # The desired net power of all inverters would supply more power to the main grid than its fuse can handle
        power_exceeded = PBSapp_net_power - PBSlim_max # strictly positive

        # Solution: check for inverters in PBSapp with a positive power level (ie. discharging battery inverters and solar inverters)
        # and check if we can be within the limit by reducing their discharge / generation power
        discharging_inverters = { i: p for i, p in PBSapp.inv_power.items() if p > 0 }
        tot_generated_power = abs(sum(discharging_inverters.values()))
        if power_exceeded <= tot_generated_power: # yes
            # modify PBSsent by reducing discharge/generation power of the inverters
            # weighted on their original PBSapp discharge level
            for inv_name, inv_PBSapp in discharging_inverters.items():
                power_reduction = abs(inv_PBSapp) / tot_generated_power * power_exceeded
                PBSsent.inv_power[inv_name] = inv_PBSapp - power_reduction

            return PBSsent

        # For now no other viable solutions.
        raise DMWException(f'insufficient control authority for safe PBSsent power: {PBSapp} > {PBSlim_max}', source='calc_PBSsent')

    raise ProgrammingError(f'should not reach here', source='calc_PBSsent')
