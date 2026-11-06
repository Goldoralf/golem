// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { activeForSelection, currentAudioForm, useDeviceValue } from './desktop-audio-model.mjs';

const settings = {
  platform: 'windows', driver: 'UMC ASIO Driver', sample_rate: 48000,
  buffer_size: 256, sample_rate_use: true, buffer_size_use: true,
  actual: { MODE: 'ASIO', IDENT_IN: 'ASIO UMC ASIO Driver',
    IDENT_OUT: 'ASIO UMC ASIO Driver', SRATE: '44100', BSIZE: '128' },
};

test('the editor opens with effective REAPER values', () => {
  assert.equal(currentAudioForm(settings).sample_rate, 44100);
  assert.equal(currentAudioForm(settings).buffer_size, 128);
});

test('Use device value disables a request and reads the current value', () => {
  const form = useDeviceValue(settings, 'buffer_size', true);
  assert.equal(form.buffer_size_use, false);
  assert.equal(form.buffer_size, 128);
  assert.equal(useDeviceValue(form, 'buffer_size', false).buffer_size_use, true);
});

test('another selected driver never inherits the active driver values', () => {
  const other = { ...settings, driver: 'ASIO4ALL v2' };
  assert.equal(activeForSelection(other), null);
  assert.equal(currentAudioForm(other).buffer_size, 256);
});
