export const ROLE_LABELS = {
  admin: 'Administrator', doctor: 'Doctor', nurse: 'Nurse',
  coordinator: 'ICU Coordinator / Head Nurse', researcher: 'Researcher / Reviewer',
}
export function permissions(role) {
  return { patients: ['admin', 'doctor', 'nurse', 'coordinator'].includes(role),
    unit: ['admin', 'coordinator'].includes(role), accounts: role === 'admin',
    events: role === 'doctor' ? ['review', 'acknowledge'] : role === 'nurse' ? ['observation', 'acknowledge']
      : role === 'coordinator' ? ['handover', 'acknowledge'] : [] }
}
