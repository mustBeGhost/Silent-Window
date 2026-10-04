import assert from 'node:assert/strict'
import { test } from 'node:test'
import { usernameError } from '../src/utils/accountValidation.js'

test('new usernames start with lowercase letters and allow optional numbers', () => {
  for (const name of ['admin', 'admin12', 'a12', 'a'.repeat(32)]) assert.equal(usernameError(name), null, name)
  for (const name of ['', 'ab', '1admin', '123', 'Admin', 'admin_name', 'admin-name', 'admin.name', 'admin name', ' admin', 'álpha', 'a'.repeat(33)]) {
    assert.match(usernameError(name), /Start with a lowercase letter/, name)
  }
})

test('duplicate usernames warn even when an existing account is inactive or uses legacy uppercase', () => {
  assert.match(usernameError('admin', ['Admin']), /already in use/)
  assert.match(usernameError('doctor2', ['doctor2']), /Choose another/)
  assert.equal(usernameError('doctor3', ['doctor2']), null)
})
