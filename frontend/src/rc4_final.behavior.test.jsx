/**
 * M2.6 RC4 final bug fixes.
 *
 *   #82  an HTTP refusal whose body is not JSON is a known refusal, not an
 *        unknown-outcome network error: the loaded dataset survives, no
 *        revision-bound clear is sent, and the same file can be retried.
 *   #83  the bundled sample catalog is authoritative for the operation a
 *        sample declares, even when /api/meta is unavailable. An operation
 *        that cannot be established blocks the run instead of silently
 *        using the previously selected one.
 */

import { beforeAll, afterEach, describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup, act } from '@testing-library/react';
import App from './App.jsx';

beforeAll(() => {
  if (!window.ResizeObserver) {
    window.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const META = {
  version: '9.9.9-test',
  default_engine: 'bedtools',
  max_file_size_mb: 500,
  assemblies: [],
  naming_options: [{ key: null, label: 'Keep original names' }],
  modes: [
    { key: 'overlap', label: 'Overlap' },
    { key: 'contains', label: 'Contains' },
    { key: 'within', label: 'Within' },
    { key: 'closest', label: 'Closest' },
  ],
};

const SAMPLE_CATALOG = [
  { id: 'gene_overlap', name: 'Gene Overlap Analysis', mode: 'overlap' },
  { id: 'closest_variants', name: 'Closest Variants Proximity', mode: 'closest' },
  { id: 'stranded_features', name: 'Strand-Specific Features', mode: 'overlap' },
];

const dataset = (filename, format, totalRows, revision, extra = {}) => ({
  filename,
  format,
  total_rows: totalRows,
  columns: ['chr', 'start', 'end'],
  preview: [{ chr: 'chr1', start: 9, end: 20 }],
  needs_mapping: false,
  ...(revision ? { revision } : {}),
  ...extra,
});

const EXEC_RESULT = {
  status: 'success',
  result_revision: 'result-rev-1',
  query_revision: 'sample-query-rev',
  annot_revision: 'sample-annot-rev',
  registry: { source: 'none', revision: null, digest: null, name: null, row_count: null, assembly: null },
  stats: {
    elapsed_seconds: 0.42,
    engine: 'bedtools',
    mode: 'closest',
    join: 'left',
    matched_query_count: 1,
    query_count: 1,
    result_count: 1,
    unmatched_query_count: 0,
    match_rate: 100,
  },
  warnings: [],
  feature_filter: null,
  gene_list: { gene_column: null, genes: [], top10: [] },
  chromosome_normalization: null,
  columns: ['coord_chr', 'coord_start', 'coord_end'],
  preview: [{ coord_chr: 'chr1', coord_start: 9, coord_end: 20 }],
  total_rows: 1,
  charts: { chromosome_distribution: [], match_ratio: [] },
};

const jsonResponse = (payload, { status = 200 } = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: { get: () => null },
  text: async () => JSON.stringify(payload),
  json: async () => payload,
});

// A response the server *did* send, with a body that is not JSON. `json` is
// deliberately provided and deliberately rejects, so this fixture also
// reproduces the pre-fix res.json() failure.
const nonJsonResponse = (body, status) => ({
  ok: false,
  status,
  headers: { get: () => null },
  text: async () => body,
  json: async () => {
    throw new SyntaxError('Unexpected token < in JSON');
  },
});

const renderApp = async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText('v9.9.9-test')).toBeTruthy());
};

const renderAppWithoutMeta = async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByLabelText('Bundled sample dataset')).toBeTruthy());
};

const fileInputs = () => document.querySelectorAll('input[type="file"]');

const chooseFile = (role, file) => {
  const index = role === 'query' ? 0 : 1;
  fireEvent.change(fileInputs()[index], { target: { files: [file] } });
};

const uploadQuery = (name) => chooseFile('query', new File(['chr1\t10\t20\n'], name));

const runButton = () => screen.getByRole('button', { name: 'Run annotation' });

const sampleSelect = () => screen.getByLabelText('Bundled sample dataset');

const selectWithOption = (text) => {
  const select = screen.getAllByRole('combobox').find((s) =>
    Array.from(s.options).some((o) => o.textContent.trim() === text),
  );
  if (!select) throw new Error(`no select with option ${text}`);
  return select;
};

const chooseOption = (text) => {
  const select = selectWithOption(text);
  const option = Array.from(select.options).find((o) => o.textContent.trim() === text);
  fireEvent.change(select, { target: { value: option.value } });
  return select;
};

const coordSelects = () =>
  screen.getAllByRole('combobox').filter(
    (s) => s.options.length === 3 && s.options[0].value === 'Auto-detect',
  );

const loadSample = async (id) => {
  await waitFor(() => expect(sampleSelect().value).toBeTruthy());
  fireEvent.change(sampleSelect(), { target: { value: id } });
  fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
};

const SAMPLE_PAYLOAD = {
  query: {
    ...dataset('example_closest_variants.vcf', 'vcf', 4, 'sample-query-rev'),
    coordinate_system: '1-based',
  },
  annot: {
    ...dataset('example_closest_annotations.gff3', 'gff3', 3, 'sample-annot-rev'),
    coordinate_system: '1-based',
  },
};

// ---------------------------------------------------------------------------
// #82: non-JSON HTTP refusals
// ---------------------------------------------------------------------------

const uploadBackend = (uploadResponses) => {
  const calls = { uploads: [], clears: [], executes: [] };
  let nextUpload = 0;
  const fetchStub = vi.fn((url, options = {}) => {
    const u = String(url);
    if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
    if (u === '/api/sample-datasets') return Promise.resolve(jsonResponse([]));
    if (u === '/api/upload') {
      calls.uploads.push({ role: options.body.get('role'), name: options.body.get('file')?.name });
      const response = uploadResponses[nextUpload++];
      if (response instanceof Error) return Promise.reject(response);
      return Promise.resolve(response);
    }
    if (u === '/api/dataset/clear') {
      calls.clears.push(JSON.parse(options.body));
      return Promise.resolve(jsonResponse({ status: 'success' }));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal('fetch', fetchStub);
  return { calls };
};

const refusalMessage = (status) => new RegExp(`HTTP ${status}`);

describe('#82: an HTTP refusal with a non-JSON body keeps the loaded dataset', () => {
  const HTML_413 = '<!doctype html><html><body><h1>413 Request Entity Too Large</h1></body></html>';

  it('handles HTTP 413 with an HTML proxy page as a known refusal', async () => {
    const b = uploadBackend([
      jsonResponse(dataset('valid.bed', 'bed', 2, 'query-rev-1')),
      nonJsonResponse(HTML_413, 413),
    ]);
    await renderApp();

    uploadQuery('valid.bed');
    await waitFor(() => expect(screen.getByText('valid.bed')).toBeTruthy());

    uploadQuery('refused.bed');
    await waitFor(() => expect(screen.getByText(refusalMessage(413))).toBeTruthy());

    expect(screen.getByText('valid.bed')).toBeTruthy();
    expect(b.calls.clears).toEqual([]);
    expect(document.body.textContent).not.toContain('Request Entity Too Large');
    expect(document.body.textContent).not.toContain('<!doctype html>');
  });

  it('handles HTTP 400 with a plain-text proxy body as a known refusal', async () => {
    const b = uploadBackend([
      jsonResponse(dataset('valid.bed', 'bed', 2, 'query-rev-1')),
      nonJsonResponse('Bad Request from reverse proxy', 400),
    ]);
    await renderApp();

    uploadQuery('valid.bed');
    await waitFor(() => expect(screen.getByText('valid.bed')).toBeTruthy());

    uploadQuery('refused.bed');
    await waitFor(() => expect(screen.getByText(refusalMessage(400))).toBeTruthy());

    expect(screen.getByText('valid.bed')).toBeTruthy();
    expect(b.calls.clears).toEqual([]);
    expect(document.body.textContent).not.toContain('Bad Request from reverse proxy');
  });

  it('handles HTTP 500 with an empty body as a known refusal', async () => {
    const b = uploadBackend([
      jsonResponse(dataset('valid.bed', 'bed', 2, 'query-rev-1')),
      nonJsonResponse('', 500),
    ]);
    await renderApp();

    uploadQuery('valid.bed');
    await waitFor(() => expect(screen.getByText('valid.bed')).toBeTruthy());

    uploadQuery('refused.bed');
    await waitFor(() => expect(screen.getByText(refusalMessage(500))).toBeTruthy());

    expect(screen.getByText('valid.bed')).toBeTruthy();
    expect(b.calls.clears).toEqual([]);
  });

  it('handles malformed JSON on a non-OK response as a known refusal', async () => {
    const b = uploadBackend([
      jsonResponse(dataset('valid.bed', 'bed', 2, 'query-rev-1')),
      nonJsonResponse('{"detail": ', 502),
    ]);
    await renderApp();

    uploadQuery('valid.bed');
    await waitFor(() => expect(screen.getByText('valid.bed')).toBeTruthy());

    uploadQuery('refused.bed');
    await waitFor(() => expect(screen.getByText(refusalMessage(502))).toBeTruthy());

    expect(screen.getByText('valid.bed')).toBeTruthy();
    expect(b.calls.clears).toEqual([]);
  });

  it('keeps the valid dataset through every known HTTP refusal and sends no clear', async () => {
    const refusals = [
      nonJsonResponse(HTML_413, 413),
      nonJsonResponse('plain text refusal', 400),
      nonJsonResponse('', 500),
      nonJsonResponse('{"detail": ', 502),
    ];
    const b = uploadBackend([
      jsonResponse(dataset('valid.bed', 'bed', 2, 'query-rev-1')),
      ...refusals,
    ]);
    await renderApp();

    uploadQuery('valid.bed');
    await waitFor(() => expect(screen.getByText('valid.bed')).toBeTruthy());

    for (const response of refusals) {
      uploadQuery(`refused-${response.status}.bed`);
      await waitFor(() => expect(screen.getByText(refusalMessage(response.status))).toBeTruthy());
      expect(screen.getByText('valid.bed')).toBeTruthy();
    }
    expect(b.calls.clears).toEqual([]);
  });

  it('keeps both loaded sides when /api/load-sample answers with non-JSON', async () => {
    let sampleLoads = 0;
    const clears = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url, options = {}) => {
        const u = String(url);
        if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
        if (u === '/api/sample-datasets') return Promise.resolve(jsonResponse(SAMPLE_CATALOG));
        if (u === '/api/load-sample') {
          sampleLoads += 1;
          return Promise.resolve(
            sampleLoads === 1 ? jsonResponse(SAMPLE_PAYLOAD) : nonJsonResponse('<html>gateway</html>', 502),
          );
        }
        if (u === '/api/dataset/clear') {
          clears.push(JSON.parse(options.body));
          return Promise.resolve(jsonResponse({ status: 'success' }));
        }
        return Promise.resolve(jsonResponse({}));
      }),
    );
    await renderApp();
    await waitFor(() => expect(sampleSelect().value).toBeTruthy());

    await loadSample('closest_variants');
    await waitFor(() => expect(screen.getByText('example_closest_variants.vcf')).toBeTruthy());

    // The second load is refused by an HTTP response without a JSON body. The
    // sample data already loaded is the previous state and must survive.
    fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
    await waitFor(() => expect(screen.getByText(/HTTP 502/)).toBeTruthy());

    expect(screen.getByText('example_closest_variants.vcf')).toBeTruthy();
    expect(screen.getByText('example_closest_annotations.gff3')).toBeTruthy();
    expect(clears).toEqual([]);
    expect(document.body.textContent).not.toContain('gateway');
  });

  it('still treats a true network rejection as an unknown outcome', async () => {
    const b = uploadBackend([
      jsonResponse(dataset('valid.bed', 'bed', 2, 'query-rev-1')),
      new TypeError('network down'),
    ]);
    await renderApp();

    uploadQuery('valid.bed');
    await waitFor(() => expect(screen.getByText('valid.bed')).toBeTruthy());

    uploadQuery('unknown.bed');
    await waitFor(() => expect(screen.getByText(/Network error uploading file/)).toBeTruthy());

    expect(screen.queryByText('valid.bed')).toBeNull();
    expect(b.calls.clears).toEqual([{ role: 'query', revision: 'query-rev-1' }]);
  });

  it('keeps the same file retryable after a non-JSON refusal', async () => {
    const b = uploadBackend([
      nonJsonResponse(HTML_413, 413),
      jsonResponse(dataset('same.bed', 'bed', 2, 'retry-rev')),
    ]);
    await renderApp();

    const same = new File(['chr1\t10\t20\n'], 'same.bed');
    chooseFile('query', same);
    await waitFor(() => expect(screen.getByText(refusalMessage(413))).toBeTruthy());

    // The picker was remounted, so selecting the very same File object fires
    // a change event again and reaches the server.
    chooseFile('query', same);
    await waitFor(() => expect(screen.getByText(/Parsed same.bed/)).toBeTruthy());

    expect(b.calls.uploads.map((u) => u.name)).toEqual(['same.bed', 'same.bed']);
    expect(b.calls.clears).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// #83: the sample catalog is authoritative for its declared operation
// ---------------------------------------------------------------------------

const sampleBackend = ({
  meta = META,
  metaFails = false,
  samples = SAMPLE_CATALOG,
  loadSample = SAMPLE_PAYLOAD,
  execute = EXEC_RESULT,
  pendingSample = false,
} = {}) => {
  const calls = { sampleLoads: [], executes: [], uploads: [], clears: [], pending: [] };
  const fetchStub = vi.fn((url, options = {}) => {
    const u = String(url);
    if (u === '/api/meta') {
      return metaFails ? Promise.reject(new TypeError('meta unavailable')) : Promise.resolve(jsonResponse(meta));
    }
    if (u === '/api/sample-datasets') return Promise.resolve(jsonResponse(samples));
    if (u === '/api/load-sample') {
      calls.sampleLoads.push(options.body.get('sample_id'));
      if (pendingSample) {
        return new Promise((resolve) => calls.pending.push(resolve));
      }
      return Promise.resolve(jsonResponse(loadSample));
    }
    if (u === '/api/upload') {
      calls.uploads.push({ role: options.body.get('role'), name: options.body.get('file')?.name });
      return Promise.resolve(jsonResponse(dataset('newer.bed', 'bed', 1, 'newer-rev')));
    }
    if (u === '/api/dataset/clear') {
      calls.clears.push(JSON.parse(options.body));
      return Promise.resolve(jsonResponse({ status: 'success' }));
    }
    if (u === '/api/execute') {
      calls.executes.push(JSON.parse(options.body));
      return Promise.resolve(jsonResponse(execute));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal('fetch', fetchStub);
  return { calls };
};

const operationSelect = () => selectWithOption('Overlap');
const operationValue = () => operationSelect().value;

describe('#83: a sample declares its operation, not /api/meta', () => {
  it('/api/meta fails but the sample catalog still arrives', async () => {
    sampleBackend({ metaFails: true });
    await renderAppWithoutMeta();

    await waitFor(() =>
      expect(Array.from(sampleSelect().options).map((o) => o.value)).toEqual([
        'gene_overlap',
        'closest_variants',
        'stranded_features',
      ]),
    );
  });

  it('loads closest_variants as closest and executes with that operation when /api/meta fails', async () => {
    const b = sampleBackend({ metaFails: true });
    await renderAppWithoutMeta();
    await waitFor(() => expect(sampleSelect().value).toBeTruthy());

    await loadSample('closest_variants');
    await waitFor(() => expect(screen.getByText('example_closest_variants.vcf')).toBeTruthy());

    expect(operationValue()).toBe('closest');
    // The sample's applied coordinate convention is provenance only.
    expect(coordSelects()[0].value).toBe('Auto-detect');
    expect(coordSelects()[1].value).toBe('Auto-detect');

    expect(runButton().disabled).toBe(false);
    fireEvent.click(runButton());
    await waitFor(() => expect(b.calls.executes).toHaveLength(1));
    expect(b.calls.executes[0].mode).toBe('closest');
  });

  it('gene_overlap switches from closest back to its declared overlap', async () => {
    const b = sampleBackend();
    await renderApp();
    await waitFor(() => expect(sampleSelect().value).toBeTruthy());

    await loadSample('closest_variants');
    await waitFor(() => expect(operationValue()).toBe('closest'));

    await loadSample('gene_overlap');
    await waitFor(() => expect(b.calls.sampleLoads).toEqual(['closest_variants', 'gene_overlap']));
    await waitFor(() => expect(operationValue()).toBe('overlap'));
  });

  it('stranded_features follows the operation its catalog entry declares', async () => {
    const samples = SAMPLE_CATALOG.map((s) =>
      s.id === 'stranded_features' ? { ...s, mode: 'within' } : s,
    );
    const b = sampleBackend({ samples });
    await renderApp();
    await waitFor(() => expect(sampleSelect().value).toBeTruthy());

    await loadSample('stranded_features');
    await waitFor(() => expect(b.calls.sampleLoads).toEqual(['stranded_features']));
    await waitFor(() => expect(operationValue()).toBe('within'));
  });

  it.each([
    ['unknown operation', { ...SAMPLE_CATALOG[1], id: 'mystery_mode', mode: 'mystery' }],
    ['missing operation', { ...SAMPLE_CATALOG[1], id: 'missing_mode', mode: undefined }],
  ])('%s cannot produce a run with the previously selected operation', async (_label, sample) => {
    const b = sampleBackend({ samples: [sample], loadSample: SAMPLE_PAYLOAD });
    await renderApp();
    await waitFor(() => expect(sampleSelect().value).toBe(sample.id));

    fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
    await waitFor(() => expect(b.calls.sampleLoads).toEqual([sample.id]));

    // The data loaded, but the operation could not be established safely, so
    // the run is blocked with a recovery message instead of silently using
    // whatever operation happened to be selected.
    await waitFor(() =>
      expect(screen.getAllByText(/Run is disabled/i).length).toBeGreaterThan(0),
    );
    expect(runButton().disabled).toBe(true);
    fireEvent.click(runButton());
    await waitFor(() => expect(b.calls.executes).toEqual([]));
  });

  it('a stale sample response cannot overwrite a newer operation', async () => {
    const b = sampleBackend({ pendingSample: true });
    await renderApp();
    await waitFor(() => expect(sampleSelect().value).toBeTruthy());

    await loadSample('closest_variants');
    await waitFor(() => expect(b.calls.pending).toHaveLength(1));

    // The user chooses a newer operation ...
    chooseOption('Within');
    expect(operationValue()).toBe('within');

    // ... and a newer request supersedes the pending sample load.
    chooseFile('query', new File(['chr1\t1\t2\n'], 'newer.bed'));
    await waitFor(() => expect(b.calls.uploads).toHaveLength(1));

    // The old sample response arrives last. It is stale and must not apply
    // its declared closest operation over the newer one.
    await act(async () => b.calls.pending[0](jsonResponse(SAMPLE_PAYLOAD)));
    expect(operationValue()).toBe('within');
    expect(b.calls.executes).toEqual([]);
  });
});
