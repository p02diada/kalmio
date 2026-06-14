export type VehicleSettings = {
  model: string
  battery: number | null
  usable_battery_kwh: number | null
  consumption_kwh_per_100km: number | null
  connector: string
  max_charge_kw: number | null
}

export type CompleteVehicleSettings = VehicleSettings & {
  model: string
  battery: number
  usable_battery_kwh: number
  consumption_kwh_per_100km: number
  connector: string
  max_charge_kw: number
}

export type PreferenceSettings = {
  reserve_min_percent: number
  prefer_fast: boolean
  prefer_cheap: boolean
  prefer_low_stress: boolean
  avoid_single_connector: boolean
  prefer_services: boolean
  prefer_large_hubs: boolean
}

export const emptyVehicle: VehicleSettings = {
  model: '',
  battery: null,
  usable_battery_kwh: null,
  consumption_kwh_per_100km: null,
  connector: '',
  max_charge_kw: null,
}

export const defaultPreferences: PreferenceSettings = {
  reserve_min_percent: 20,
  prefer_fast: false,
  prefer_cheap: false,
  prefer_low_stress: true,
  avoid_single_connector: true,
  prefer_services: true,
  prefer_large_hubs: true,
}

export function vehicleSettingsComplete(vehicle: VehicleSettings): vehicle is CompleteVehicleSettings {
  return (
    vehicle.model.trim().length > 0 &&
    vehicle.connector.trim().length > 0 &&
    vehicle.battery !== null &&
    vehicle.usable_battery_kwh !== null &&
    vehicle.consumption_kwh_per_100km !== null &&
    vehicle.max_charge_kw !== null
  )
}

export function missingVehicleFields(vehicle: VehicleSettings): string[] {
  const missing: string[] = []
  if (!vehicle.model.trim()) missing.push('modelo')
  if (vehicle.battery === null) missing.push('batería actual')
  if (vehicle.usable_battery_kwh === null) missing.push('batería útil')
  if (vehicle.consumption_kwh_per_100km === null) missing.push('consumo')
  if (!vehicle.connector.trim()) missing.push('conector')
  if (vehicle.max_charge_kw === null) missing.push('potencia máxima')
  return missing
}
