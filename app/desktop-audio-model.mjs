// SPDX-License-Identifier: GPL-3.0-or-later
// Les valeurs de reaper.ini sont des demandes ; celles du moteur ouvert font foi.
export const activeForSelection = settings => {
  const actual = settings.actual;
  if (!actual || !actual.MODE) return null;
  if (settings.platform === 'windows') {
    const opened = `${actual.IDENT_IN || ''} ${actual.IDENT_OUT || ''}`.toLowerCase();
    return actual.MODE.toUpperCase() === 'ASIO' && settings.driver &&
      opened.includes(settings.driver.toLowerCase()) ? actual : null;
  }
  return actual;
};

export const currentAudioForm = settings => {
  const actual = activeForSelection(settings);
  return { ...settings,
    sample_rate: Number(actual?.SRATE) || settings.sample_rate,
    buffer_size: Number(actual?.BSIZE) || settings.buffer_size };
};

export const useDeviceValue = (form, key, checked) => {
  const actual = activeForSelection(form);
  const reported = key === 'sample_rate' ? actual?.SRATE : actual?.BSIZE;
  return { ...form, [`${key}_use`]: !checked,
    [key]: Number(reported) || form[key] };
};
