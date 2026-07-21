from collections import Counter
from dataclasses import dataclass, field

from .definitions import Phase
from .exceptions import ProgrammingError
from .base_inverter import BaseInverter


@dataclass
class PhasePowerMap:
    '''
    Mapping of power level for all (B)attery and (S)olar inverters connected to a
    single phase. Can be used for:
        - desired (PBSapp) power level
        - measured (PBSnow) power level
        - safe (PBSsent) power level
    '''
    phase: Phase
    inv_power: dict[str, float] = field(default_factory=dict)

    @property
    def net_power(self) -> float:
        return sum(self.inv_power.values())

    def __str__(self) -> str:
        return f'{self.phase}: ' + ', '.join(f'{i}: {p:.0f}W' for i, p in self.inv_power.items())

    def copy(self) -> 'PhasePowerMap':
        return PhasePowerMap(phase=self.phase, inv_power={ n: p for n, p in self.inv_power.items() })


class PBSapp:
    '''
    Class capturing the desired power level for both (B)attery and (S)olar inverters.
    Power level is expressed in Watts and be both positive (power sourced from the inverter)
    as well as negative (power sunk into the device).
    '''
    def __init__(self,
        inverters: list[BaseInverter]
    ):
        self.L1 = PhasePowerMap(phase=Phase.L1)
        self.L2 = PhasePowerMap(phase=Phase.L2)
        self.L3 = PhasePowerMap(phase=Phase.L3)

        self.inverters: dict[str, BaseInverter] = {}
        for inv in inverters:
            if not isinstance(inv, BaseInverter):
                raise ProgrammingError(f'passed {inv} is not an BaseInverter', source='PBSapp')
            self.inverters[inv.name] = inv

    @property
    def inverter_names(self) -> list[str]:
        return list(self.inverters.keys())

    def reset(self):
        self.L1 = PhasePowerMap(phase=Phase.L1)
        self.L2 = PhasePowerMap(phase=Phase.L2)
        self.L3 = PhasePowerMap(phase=Phase.L3)

    def __getitem__(self, phase: Phase) -> PhasePowerMap:
        if not isinstance(phase, Phase) or phase == Phase.ALL:
            raise ProgrammingError(f'invalid usage of PBSapp, passed: {phase}', source='pbsapp')

        if phase == Phase.L1:
            return self.L1
        elif phase == Phase.L2:
            return self.L2
        else: # L3
            return self.L3

    def __setitem__(self, phase: Phase, value: PhasePowerMap):
        if not isinstance(phase, Phase) or not isinstance(value, PhasePowerMap) or phase == Phase.ALL:
            raise ProgrammingError(f'invalid usage of PBSapp, passed: {phase}', source='pbsapp')

        if phase == Phase.L1:
            self.L1 = value
        elif phase == Phase.L2:
            self.L2 = value
        else: # L3
            self.L3 = value

    def copy(self) -> 'PBSapp':
        '''
        Return a new PBSapp with an independent copy of the per-phase power maps.
        The underlying inverter objects are shared (referenced), not duplicated.
        '''
        new = PBSapp(list(self.inverters.values()))
        new.L1 = self.L1.copy()
        new.L2 = self.L2.copy()
        new.L3 = self.L3.copy()
        return new

    def set(self, phase: Phase, inverter: str, power: float):
        '''
        Set the desired power level for a given inverter connected to the given phase.
        If ALL is passed as phase, then the same power level is applied to each of the three phases
        '''
        if inverter not in self.inverters:
            raise ProgrammingError(f'unable to set power level for inverter {inverter}, not set in constructor', source='PBSapp')

        safe_power = self.inverters[inverter].apply_power_limits(power)

        if phase == Phase.ALL:
            self.L1.inv_power[inverter] = safe_power
            self.L2.inv_power[inverter] = safe_power
            self.L3.inv_power[inverter] = safe_power

        elif phase == Phase.L1:
            self.L1.inv_power[inverter] = safe_power

        elif phase == Phase.L2:
            self.L2.inv_power[inverter] = safe_power

        else: # L3
            self.L3.inv_power[inverter] = safe_power

    def get(self, phase: Phase, inverter: str) -> float:
        '''
        Get the desired power level for a given inverter connected to the given phase.
        '''
        if inverter not in self.inverters:
            raise ProgrammingError(f'unable to get power level for inverter {inverter}, not set in constructor', source='PBSapp')
        if not isinstance(phase, Phase) or phase == Phase.ALL:
            raise ProgrammingError(f'unable to get power level for inverter, invalid phase {phase}', source='PBSapp')

        if phase == Phase.L1:
            if inverter not in self.L1.inv_power:
                raise ProgrammingError(f'unable to get power level for inverter {inverter}, not yet set', source='PBSapp')
            return self.L1.inv_power[inverter]
        if phase == Phase.L2:
            if inverter not in self.L2.inv_power:
                raise ProgrammingError(f'unable to get power level for inverter {inverter}, not yet set', source='PBSapp')
            return self.L2.inv_power[inverter]
        else: # L3
            if inverter not in self.L3.inv_power:
                raise ProgrammingError(f'unable to get power level for inverter {inverter}, not yet set', source='PBSapp')
            return self.L3.inv_power[inverter]

    def get_inverter_phases(self, inverter: str) -> list[Phase]:
        ret = []

        if inverter in self.L1.inv_power:
            ret.append(Phase.L1)
        if inverter in self.L2.inv_power:
            ret.append(Phase.L2)
        if inverter in self.L3.inv_power:
            ret.append(Phase.L3)

        return ret

    def get_multiphase_inverters(self) -> list[str]:
        '''
        Return a list of inverter names which are connected to more than one phase
        '''
        counts = Counter()
        for ppm in (self.L1, self.L2, self.L3):
            counts.update(ppm.inv_power.keys())
        return [name for name, count in counts.items() if count >= 2]
