export const USERNAME_HINT = '3–32 characters. Start with a lowercase letter. Use lowercase letters and optional numbers only, for example admin12.'

export function usernameError(value, existingUsernames = []) {
  if (!/^[a-z][a-z0-9]{2,31}$/.test(value)) return USERNAME_HINT
  if (existingUsernames.some((name) => name.toLowerCase() === value.toLowerCase())) {
    return 'That username is already in use. Choose another username.'
  }
  return null
}
