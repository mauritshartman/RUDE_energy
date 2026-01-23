from prettytable import PrettyTable


def calc_PBsent(
    PBapp: int,
    PBnow: float,
    PGnow: float,
    VGnow: float,
    Imax: int,
    col_header: str = '',
    table: PrettyTable | None = None,
) -> float:
    '''Calculate safe charge/discharge amount (PBsent) based on desired (PBapp) amount, in the
    current system context.

    Parameters:
    -----------
    PBapp: int
        Desired charge (negative) or discharge (positive) amount in W
    PBnow: float
        Power at the battery inverter. Can be negative (charging the battery) or positive (discharging)
    PGnow: float
        Power at grid connection. Can be negative (drawing power from grid) or positive (supplying power)
    VGnow: float
        Measured voltage at grid connection point. Alway a positive value
    Imax: float
        Main fuse current limit at grid connection. Always a positive value

    Returns:
    --------
    float
        The safe charge / discharge amount (PBsent) that can be commanded to the battery inverter
    '''
    PGmax = abs(VGnow * Imax)
    PGmin = -1 * PGmax
    Pother = PGnow - PBnow  # Power consumed (negative value) or supplied (positive) elsewhere in the system (eg. heat pump or PV)
    PBlim_min = PGmin - Pother  # lower limit for battery inverter power value when charging/discharging
    PBlim_max = PGmax - Pother  # upper limit for battery inverter power value when charging/discharging

    if PBapp < 0:  # negative so a desire to charge the battery
        PBsent = int(max(PBapp, PBlim_min))
    else:  # positive so a desire to charge the battery
        PBsent = int(min(PBapp, PBlim_max))

    if table is not None:
        table.add_column(col_header, [
            PBapp,
            f'{PBnow:.0f} W',
            f'{PGnow:.0f} W',
            f'{VGnow:.1f} V',
            f'{Imax:.0f} I',
            f'{PGmax:.0f} W',
            f'{PGmin:.0f} W',
            f'{Pother:.0f} W',
            f'{PBlim_min:.0f} W',
            f'{PBlim_max:.0f} W',
            f'{PBsent:.0f} W',
        ])
        table.align[col_header] = 'r'

    return PBsent