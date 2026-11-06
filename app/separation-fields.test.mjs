// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fillFields, fieldsMissing } from './separation-fields.js';

const fields = [
  { token: '{model}', required: true },
  { token: '{models_dir}', required: false, drop: ['--model_file_dir'] },
];
const args = ['{input}', '--model_filename', '{model}', '--model_file_dir', '{models_dir}', '--output_dir', '{outdir}'];

test('a filled model replaces its token', () => {
  assert.deepEqual(fillFields(args, fields, { '{model}': ' m.cfg ', '{models_dir}': '/m' }),
    ['{input}', '--model_filename', 'm.cfg', '--model_file_dir', '/m', '--output_dir', '{outdir}']);
});
test('an empty optional field drops its option too', () => {
  assert.deepEqual(fillFields(args, fields, { '{model}': 'm.cfg' }),
    ['{input}', '--model_filename', 'm.cfg', '--output_dir', '{outdir}']);
});
test('an empty model is missing, and stays a token', () => {
  assert.deepEqual(fieldsMissing(args, fields, {}).map(f => f.token), ['{model}']);
  assert.ok(fillFields(args, fields, {}).includes('{model}'));
  assert.deepEqual(fieldsMissing(args, fields, { '{model}': 'x' }), []);
});
