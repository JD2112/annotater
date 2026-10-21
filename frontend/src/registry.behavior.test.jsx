import { beforeAll, afterEach, describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup, act, within } from '@testing-library/react';
import App from './App.jsx';

// recharts' ResponsiveContainer relies on ResizeObserver, which jsdom does not
// provide; a no-op observer is enough for rendering assertions.
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
  delete URL.createObjectURL;
  delete URL.revokeObjectURL;
});

const jsonResponse = (payload, { status = 200, ok = true, headers = {} } = {}) => ({
  ok,
  status,
  headers: { get: (name) => headers[name] ?? headers[name?.toLowerCase()] ?? null },
  json: async () => payload,
});

const errorResponse = (status, detail, headers = {}) =>
  jsonResponse({ detail }, { ok: false, status, headers });

const META = {
  version: '9.9.9-test',
  default_engine: 'polars-bio',
  assemblies: [
    {
      id: 'hg38',
      display_label: 'Human GRCh38 (hg38)',
      scientific_name: 'Homo sapiens',
      ucsc_db: 'hg38',
    },
  ],
  naming_options: [
    { key: null, label: 'Keep original names' },
    { key: 'ucsc', label: 'UCSC names' },
    { key: 'ensembl', label: 'Ensembl names' },
  ],
};

// The bundled sample catalog served by GET /api/sample-datasets. The frontend
// reads the sample ids, names and declared operations from this endpoint, so
// the fixture mirrors the server's catalog shape exactly.
const SAMPLE_CATALOG = [
  { id: 'gene_overlap', name: 'Gene Overlap Analysis', mode: 'overlap' },
  { id: 'closest_variants', name: 'Closest Variants Proximity', mode: 'closest' },
  { id: 'stranded_features', name: 'Strand-Specific Features', mode: 'overlap' },
];

const dataset = (filename, format, totalRows, revision) => ({
  filename,
  format,
  total_rows: totalRows,
  columns: ['chr', 'start', 'end'],
  preview: [{ chr: 'chr1', start: 9, end: 20 }],
  needs_mapping: false,
  ...(revision ? { revision } : {}),
});

const REGISTRY = (revision = 'reg-rev-1', digest = 'digest-a', rowCount = 2) => ({
  source: 'custom',
  revision,
  digest,
  name: 'Custom chromosome mapping',
  row_count: rowCount,
  assembly: null,
});

const NONE_REGISTRY = {
  source: 'none',
  revision: null,
  digest: null,
  name: null,
  row_count: null,
  assembly: null,
};

const BUNDLED_REGISTRY = {
  source: 'bundled',
  revision: null,
  digest: null,
  name: 'Human GRCh38',
  row_count: null,
  assembly: 'hg38',
};

const EXEC_RESULT = (registry = REGISTRY()) => ({
  status: 'success',
  result_revision: 'result-rev-1',
  query_revision: 'query-rev-1',
  annot_revision: 'annot-rev-1',
  registry,
  stats: {
    elapsed_seconds: 0.42,
    engine: 'bedtools',
    mode: 'closest',
    join: 'left',
    matched_query_count: 12,
    query_count: 20,
    result_count: 20,
    unmatched_query_count: 8,
    match_rate: 60,
  },
  warnings: [],
  feature_filter: null,
  gene_list: ['BRCA1', 'TP53'],
  chromosome_normalization: null,
  columns: ['chr', 'start', 'end', 'has_overlap', 'gene_id'],
  preview: [{ chr: 'chr1', start: 10, end: 20, has_overlap: true, gene_id: 'BRCA1' }],
  charts: {
    chromosome_distribution: [{ chromosome: 'chr1', intervals: 12 }],
    match_ratio: [
      { name: 'Matched', value: 12 },
      { name: 'Unmatched', value: 8 },
    ],
  },
});

const allSelects = () => screen.getAllByRole('combobox');

const selectWithOption = (text) => {
  const select = allSelects().find((s) =>
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

const chooseChromosomeSource = () => chooseOption('Custom chromosome mapping');
const chooseNaming = (label = 'UCSC names') => chooseOption(label);
const chooseBundledAssembly = () => chooseOption('Human GRCh38 (hg38)');

const registryInput = () => screen.getByLabelText('Custom chromosome mapping TSV');
const datasetInput = (role) =>
  Array.from(document.querySelectorAll('input[type="file"]')).filter(
    (i) => i.getAttribute('accept') !== '.tsv,text/tab-separated-values',
  )[role === 'query' ? 0 : 1];

const uploadRegistry = (name = 'mapping-a.tsv', content = 'assembly\tucsc\n1\tchr1\n') => {
  fireEvent.change(registryInput(), {
    target: { files: [new File([content], name, { type: 'text/tab-separated-values' })] },
  });
};

const uploadDataset = (role, name) =>
  fireEvent.change(datasetInput(role), {
    target: { files: [new File(['chr1\t10\t20\n'], name)] },
  });

const renderApp = async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText('v9.9.9-test')).toBeTruthy());
};

const runButton = () => screen.getByRole('button', { name: 'Run annotation' });
const removeButton = () => screen.getByRole('button', { name: 'Remove mapping' });
const assemblySelect = () => selectWithOption('Custom chromosome mapping');

const deferred = () => {
  let resolve;
  const promise = new Promise((res) => { resolve = res; });
  return { promise, resolve };
};

// A deterministic registry backend. Queue an entry to script one response;
// otherwise the endpoint answers immediately with an incrementing revision.
const registryBackend = () => {
  const calls = {
    registryUploads: [],
    registryClears: [],
    datasetClears: [],
    execute: [],
    uploads: [],
  };
  const queue = { registryUpload: [], registryDelete: [], execute: [], upload: [] };
  let registryCounter = 0;
  let datasetCounter = 0;

  const defaultRegistry = (name) => {
    const n = ++registryCounter;
    const payload = REGISTRY(`reg-rev-${n}`, `digest-${n}`, 2);
    return {
      payload,
      response: jsonResponse({ status: 'success', registry: payload, reused: false }),
    };
  };

  const executeBody = (body) => {
    let registry = NONE_REGISTRY;
    if (body.registry_rev) {
      const known = calls.registryUploads.find(
        (u) => u.payload?.revision === body.registry_rev,
      );
      registry = known?.payload ?? REGISTRY(body.registry_rev);
    } else if (body.assembly) {
      registry = BUNDLED_REGISTRY;
    }
    return {
      ...EXEC_RESULT(registry),
      registry,
      query_revision: body.query_rev,
      annot_revision: body.annot_rev,
    };
  };

  const fetchStub = vi.fn((url, options = {}) => {
    const u = String(url);
    if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
    if (u === '/api/sample-datasets') return Promise.resolve(jsonResponse(SAMPLE_CATALOG));
    if (u === '/api/registry' && options.method === 'POST') {
      const name = options.body.get('file').name;
      const content = options.body.get('file');
      calls.registryUploads.push({ name, content });
      if (queue.registryUpload.length) return queue.registryUpload.shift();
      const pending = defaultRegistry(name);
      const entry = calls.registryUploads[calls.registryUploads.length - 1];
      entry.payload = pending.payload;
      entry.response = pending.response;
      return Promise.resolve(pending.response);
    }
    if (u.startsWith('/api/registry?') && options.method === 'DELETE') {
      const params = Object.fromEntries(new URL(u, 'http://x').searchParams.entries());
      calls.registryClears.push(params);
      if (queue.registryDelete.length) return queue.registryDelete.shift();
      return Promise.resolve(jsonResponse({ status: 'success', cleared: true, registry: null }));
    }
    if (u === '/api/upload') {
      const role = options.body.get('role');
      const name = options.body.get('file').name;
      calls.uploads.push({ role, name, coordSystem: options.body.get('coord_system') });
      if (queue.upload.length) return queue.upload.shift();
      const n = ++datasetCounter;
      return Promise.resolve(jsonResponse(dataset(name, 'bed', 1, `${role}-rev-${n}`)));
    }
    if (u === '/api/dataset/clear') {
      calls.datasetClears.push(JSON.parse(options.body));
      return Promise.resolve(jsonResponse({ status: 'success' }));
    }
    if (u === '/api/execute') {
      const body = JSON.parse(options.body);
      calls.execute.push(body);
      if (queue.execute.length) return queue.execute.shift();
      return Promise.resolve(jsonResponse(executeBody(body)));
    }
    if (u.startsWith('/api/export/')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: () => 'attachment; filename=annotated_intervals.csv' },
        blob: async () => new Blob(['chr,start\n']),
      });
    }
    return Promise.resolve(jsonResponse({}));
  });

  vi.stubGlobal('fetch', fetchStub);
  return { calls, queue };
};

const loadBoth = async () => {
  uploadDataset('query', 'q.bed');
  await waitFor(() => expect(screen.getByText('q.bed')).toBeTruthy());
  uploadDataset('annot', 'a.bed');
  await waitFor(() => expect(screen.getByText('a.bed')).toBeTruthy());
};

const runOnce = async () => {
  fireEvent.click(runButton());
  await waitFor(() => expect(screen.getByText(/executed in/i)).toBeTruthy());
};

describe('M2.3 custom chromosome mapping: upload and metadata', () => {
  it('uploads a valid mapping and displays its active metadata', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();

    uploadRegistry();

    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    expect(screen.getByText('digest-1')).toBeTruthy();
    expect(screen.getByText('2 sequences')).toBeTruthy();
    expect(screen.getAllByText('Custom chromosome mapping').length).toBeGreaterThan(0);
    expect(backend.calls.registryUploads.map((u) => u.name)).toEqual(['mapping-a.tsv']);
    // Saving metadata only: no fixture dataset was written or cleared.
    expect(backend.calls.datasetClears).toEqual([]);
  });

  it('keeps the valid registry when an invalid mapping is refused', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    uploadRegistry('good.tsv');
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    backend.queue.registryUpload.push(
      Promise.resolve(
        errorResponse(400, {
          code: 'invalid_mapping',
          message: 'invalid custom chromosome mapping: wrong header',
          stale: [],
          issues: [
            {
              code: 'wrong_header',
              message: 'the header must be assembly, ucsc, ensembl, genbank, refseq',
              rows: [1],
              columns: [],
            },
          ],
          more: 0,
        }),
      ),
    );
    uploadRegistry('bad.tsv');

    await waitFor(() => expect(screen.getByText(/wrong header/i)).toBeTruthy());
    expect(screen.getByText(/the header must be/i)).toBeTruthy();
    // The previous registry is still active and was never removed.
    expect(screen.getByText('reg-rev-1')).toBeTruthy();
    expect(backend.calls.registryClears).toEqual([]);
  });

  it('reuses the revision for identical content and keeps a result derived from it', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry('same.tsv');
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    await loadBoth();
    await runOnce();
    expect(screen.getAllByText('reg-rev-1').length).toBeGreaterThan(0);

    backend.queue.registryUpload.push(
      Promise.resolve(
        jsonResponse({ status: 'success', registry: REGISTRY('reg-rev-1', 'digest-1', 2), reused: true }),
      ),
    );
    uploadRegistry('same.tsv');

    await waitFor(() => expect(screen.getByText(/already active/i)).toBeTruthy());
    expect(screen.getAllByText('reg-rev-1').length).toBeGreaterThan(0);
    // Same digest never invalidates the stored result.
    expect(screen.getByText(/executed in/i)).toBeTruthy();
  });

  it('replaces the mapping for different content and invalidates only its own result', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry('one.tsv');
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    await loadBoth();
    await runOnce();

    backend.queue.registryUpload.push(
      Promise.resolve(
        jsonResponse({
          status: 'success',
          registry: REGISTRY('reg-rev-2', 'digest-different', 3),
          reused: false,
        }),
      ),
    );
    uploadRegistry('two.tsv');

    await waitFor(() => expect(screen.getByText('reg-rev-2')).toBeTruthy());
    expect(screen.getByText('digest-different')).toBeTruthy();
    expect(screen.getByText('3 sequences')).toBeTruthy();
    expect(screen.queryByText(/executed in/i)).toBeNull();
    // A replacement is a write, not a clear: no DELETE is sent.
    expect(backend.calls.registryClears).toEqual([]);
  });
});

describe('M2.3 custom chromosome mapping: revision-scoped clear', () => {
  it('clears with the owned registry revision', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Remove mapping' }));

    await waitFor(() => expect(backend.calls.registryClears).toHaveLength(1));
    expect(backend.calls.registryClears[0]).toEqual({ registry_rev: 'reg-rev-1' });
    await waitFor(() => expect(screen.getByText(/mapping removed/i)).toBeTruthy());
    expect(screen.queryByText('reg-rev-1')).toBeNull();
    // Run is now unavailable: the custom source needs an active mapping.
    expect(runButton().disabled).toBe(true);
  });

  it('a stale clear response cannot remove a newer registry', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    let resolveClear;
    backend.queue.registryDelete.push(new Promise((resolve) => { resolveClear = resolve; }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove mapping' }));
    await waitFor(() => expect(backend.calls.registryClears).toHaveLength(1));
    expect(backend.calls.registryClears[0]).toEqual({ registry_rev: 'reg-rev-1' });

    // A newer upload (a later action) replaces the mapping while the clear is
    // still in flight.
    backend.queue.registryUpload.push(
      Promise.resolve(
        jsonResponse({ status: 'success', registry: REGISTRY('reg-rev-2', 'digest-new'), reused: false }),
      ),
    );
    uploadRegistry('newer.tsv');
    await waitFor(() => expect(screen.getByText('reg-rev-2')).toBeTruthy());

    await act(async () =>
      resolveClear(jsonResponse({ status: 'success', cleared: true, registry: null })),
    );

    // The superseded clear response is ignored; the newer registry survives.
    expect(screen.getByText('reg-rev-2')).toBeTruthy();
    expect(screen.queryByText(/mapping removed/i)).toBeNull();
    expect(backend.calls.registryClears).toHaveLength(1);
  });

  it('a registry revision conflict drops the stale UI state and requires re-upload', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    await loadBoth();

    backend.queue.execute.push(
      Promise.resolve(
        errorResponse(409, {
          code: 'revision_conflict',
          message: 'The custom chromosome mapping was replaced or cleared in another tab; its result was discarded.',
          stale: ['registry'],
        }),
      ),
    );
    fireEvent.click(runButton());

    const alerts = await screen.findAllByRole('alert');
    expect(alerts.some((a) => /changed in another tab/i.test(a.textContent))).toBe(true);
    expect(alerts.some((a) => /custom chromosome mapping/i.test(a.textContent))).toBe(true);
    await waitFor(() => expect(screen.queryByText('reg-rev-1')).toBeNull());
    expect(runButton().disabled).toBe(true);
    // The datasets are untouched by a registry conflict.
    expect(screen.getByText('q.bed')).toBeTruthy();
    expect(screen.getByText('a.bed')).toBeTruthy();
    expect(backend.calls.registryClears).toEqual([]);
  });

  it('ignores an upload response that arrives after a newer upload won', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();

    let resolveOld;
    backend.queue.registryUpload.push(new Promise((resolve) => { resolveOld = resolve; }));
    uploadRegistry('old.tsv');
    await waitFor(() => expect(backend.calls.registryUploads).toHaveLength(1));

    backend.queue.registryUpload.push(
      Promise.resolve(
        jsonResponse({ status: 'success', registry: REGISTRY('reg-rev-2', 'digest-newer'), reused: false }),
      ),
    );
    uploadRegistry('newer.tsv');
    await waitFor(() => expect(screen.getByText('reg-rev-2')).toBeTruthy());

    await act(async () =>
      resolveOld(
        jsonResponse({ status: 'success', registry: REGISTRY('reg-rev-old', 'digest-old'), reused: false }),
      ),
    );

    expect(screen.getByText('reg-rev-2')).toBeTruthy();
    expect(screen.queryByText('reg-rev-old')).toBeNull();
  });
});

describe('M2.3 custom chromosome mapping: execution payload and provenance', () => {
  it('sends registry_rev without an assembly for a custom run', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    await loadBoth();

    await runOnce();

    expect(backend.calls.execute[0]).toMatchObject({
      assembly: null,
      chr_naming: 'ucsc',
      registry_rev: 'reg-rev-1',
      query_rev: 'query-rev-1',
      annot_rev: 'annot-rev-2',
    });
    expect(screen.getByText(/Custom chromosome mapping:/)).toBeTruthy();
    expect(screen.getAllByText('reg-rev-1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('digest-1').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/2 sequences/).length).toBeGreaterThan(0);
  });

  it('sends a bundled assembly without registry_rev, even when a mapping is stored', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    chooseBundledAssembly();
    await loadBoth();
    await runOnce();

    expect(backend.calls.execute[0]).toMatchObject({
      assembly: 'hg38',
      chr_naming: 'ucsc',
      registry_rev: null,
    });
    expect(screen.getByText(/Bundled assembly:/)).toBeTruthy();
    expect(screen.getByText('hg38')).toBeTruthy();
  });

  it('keeps original names: no registry_rev and no registry provenance', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    await loadBoth();

    await runOnce();

    expect(backend.calls.execute[0]).toMatchObject({
      registry_rev: null,
      chr_naming: null,
      assembly: null,
    });
    expect(screen.getByText('Keep original names · no chromosome registry')).toBeTruthy();
    expect(screen.queryByText(/Custom chromosome mapping:/)).toBeNull();
  });

  it('renders provenance from the execute response after later control changes', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    await loadBoth();
    await runOnce();

    expect(screen.getByText(/Custom chromosome mapping:/)).toBeTruthy();

    // Filtering the result table is not a chromosome-source change: the
    // provenance still comes from the response, not the current controls.
    fireEvent.click(screen.getByRole('button', { name: 'matched' }));
    expect(screen.getByText(/Custom chromosome mapping:/)).toBeTruthy();
    expect(screen.getAllByText('reg-rev-1').length).toBeGreaterThan(0);

    // Changing the source invalidates the result, and no stale custom
    // provenance may be relabelled as the newly selected source.
    chooseBundledAssembly();
    expect(screen.queryByText(/executed in/i)).toBeNull();
    expect(screen.queryByText(/Custom chromosome mapping:/)).toBeNull();
    expect(screen.queryByText(/Bundled assembly:/)).toBeNull();
  });
});

describe('M2.3 custom chromosome mapping: resource and conflict recovery', () => {
  it('shows a 413 refusal and preserves the valid registry', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    uploadRegistry('small.tsv');
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    backend.queue.registryUpload.push(
      Promise.resolve(
        errorResponse(413, {
          code: 'registry_too_large',
          message: 'The custom chromosome mapping is larger than the 64 MiB limit.',
          stale: [],
        }),
      ),
    );
    uploadRegistry('huge.tsv');

    await waitFor(() => expect(screen.getByText(/larger than the 64 MiB limit/i)).toBeTruthy());
    expect(screen.getByText('reg-rev-1')).toBeTruthy();
    expect(backend.calls.registryClears).toEqual([]);
  });

  it('shows 429 with Retry-After and never retries automatically', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    uploadRegistry('small.tsv');
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    backend.queue.registryUpload.push(
      Promise.resolve(
        errorResponse(
          429,
          {
            code: 'parse_busy',
            message: 'Another custom mapping is being parsed.',
            stale: [],
          },
          { 'Retry-After': '7' },
        ),
      ),
    );
    uploadRegistry('busy.tsv');

    await waitFor(() => expect(screen.getByText(/Retry after 7 seconds/i)).toBeTruthy());
    expect(screen.getByText('reg-rev-1')).toBeTruthy();
    // The refusal was not followed by an automatic retry.
    expect(backend.calls.registryUploads).toHaveLength(2);
  });

  it('recovers from replacement_requires_clear with an explicit clear then upload', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    uploadRegistry('one.tsv');
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    backend.queue.registryUpload.push(
      Promise.resolve(
        errorResponse(409, {
          code: 'replacement_requires_clear',
          message: 'The existing registry and the new mapping cannot coexist.',
          stale: [],
        }),
      ),
    );
    uploadRegistry('larger.tsv');

    await waitFor(() => expect(screen.getByText(/Remove the active mapping first/i)).toBeTruthy());
    // The old registry is preserved; a failed replacement is not a clear.
    expect(screen.getByText('reg-rev-1')).toBeTruthy();
    expect(backend.calls.registryClears).toEqual([]);

    fireEvent.click(screen.getByRole('button', { name: 'Remove mapping' }));
    await waitFor(() => expect(backend.calls.registryClears).toHaveLength(1));
    expect(backend.calls.registryClears[0]).toEqual({ registry_rev: 'reg-rev-1' });

    uploadRegistry('larger.tsv');
    await waitFor(() => expect(screen.getByText('reg-rev-2')).toBeTruthy());
  });

  it('treats session_expired as stale state that requires recovery', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    backend.queue.registryUpload.push(
      Promise.resolve(
        errorResponse(409, {
          code: 'session_expired',
          message: 'the session expired before the registry write committed',
          stale: ['registry'],
        }),
      ),
    );
    uploadRegistry('expired.tsv');

    await waitFor(() => expect(screen.getByText(/session expired/i)).toBeTruthy());
    expect(screen.queryByText('reg-rev-1')).toBeNull();
    expect(runButton().disabled).toBe(true);
  });
});

describe('M2.3 custom chromosome mapping: independence from datasets', () => {
  it('registry upload never changes coordinate declarations', async () => {
    const backend = registryBackend();
    await renderApp();

    const queryCoord = allSelects().find((s) =>
      Array.from(s.options).some((o) => o.value === '0-based (BED)'),
    );
    const annotCoord = allSelects().filter((s) =>
      Array.from(s.options).some((o) => o.value === '0-based (BED)'),
    )[1];
    fireEvent.change(queryCoord, { target: { value: '1-based (GFF/GTF/VCF)' } });
    fireEvent.change(annotCoord, { target: { value: '0-based (BED)' } });
    const before = [queryCoord.value, annotCoord.value];

    chooseChromosomeSource();
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    expect(queryCoord.value).toBe(before[0]);
    expect(annotCoord.value).toBe(before[1]);
    // Declaring coordinates does not touch the registry API either.
    expect(backend.calls.registryClears).toEqual([]);
  });

  it('dataset uploads and registry changes stay independent', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    await loadBoth();
    // Dataset writes do not clear or replace the registry.
    expect(screen.getByText('reg-rev-1')).toBeTruthy();
    expect(backend.calls.registryClears).toEqual([]);

    // A coordinate declaration change drops only the affected dataset.
    const queryCoord = allSelects().find((s) =>
      Array.from(s.options).some((o) => o.value === '0-based (BED)'),
    );
    fireEvent.change(queryCoord, { target: { value: '1-based (GFF/GTF/VCF)' } });
    await waitFor(() => expect(screen.queryByText('q.bed')).toBeNull());
    expect(screen.getByText('a.bed')).toBeTruthy();
    expect(screen.getByText('reg-rev-1')).toBeTruthy();
    expect(backend.calls.registryClears).toEqual([]);

    // Clearing the registry leaves the datasets alone.
    fireEvent.click(screen.getByRole('button', { name: 'Remove mapping' }));
    await waitFor(() => expect(backend.calls.registryClears).toHaveLength(1));
    expect(screen.getByText('a.bed')).toBeTruthy();
    expect(backend.calls.datasetClears.map((c) => c.role)).toEqual(['query']);
  });
});

describe('M2.3 custom chromosome mapping: operation guards and failure preservation', () => {
  it('disables Run while the registry is uploading or being removed', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    await loadBoth();
    expect(runButton().disabled).toBe(false);

    const uploading = deferred();
    backend.queue.registryUpload.push(uploading.promise);
    uploadRegistry('replacement.tsv');
    await waitFor(() => expect(registryInput().disabled).toBe(true));
    expect(runButton().disabled).toBe(true);
    expect(removeButton().disabled).toBe(true);

    await act(async () =>
      uploading.resolve(
        jsonResponse({
          status: 'success',
          registry: REGISTRY('reg-rev-2', 'digest-new'),
          reused: false,
        }),
      ),
    );
    await waitFor(() => expect(runButton().disabled).toBe(false));

    const removing = deferred();
    backend.queue.registryDelete.push(removing.promise);
    fireEvent.click(removeButton());
    await waitFor(() => expect(removeButton().disabled).toBe(true));
    expect(runButton().disabled).toBe(true);

    await act(async () =>
      removing.resolve(jsonResponse({ status: 'success', cleared: true, registry: null })),
    );
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove mapping' })).toBeNull());
    expect(runButton().disabled).toBe(true);
  });

  it('disables the registry controls while an execution is in flight', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    await loadBoth();

    const executing = deferred();
    backend.queue.execute.push(executing.promise);
    fireEvent.click(runButton());

    await waitFor(() => expect(registryInput().disabled).toBe(true));
    expect(removeButton().disabled).toBe(true);
    expect(assemblySelect().disabled).toBe(true);

    await act(async () =>
      executing.resolve(
        jsonResponse({
          ...EXEC_RESULT(REGISTRY('reg-rev-1', 'digest-1', 2)),
          query_revision: 'query-rev-1',
          annot_revision: 'annot-rev-2',
        }),
      ),
    );
    await waitFor(() => expect(registryInput().disabled).toBe(false));
    expect(removeButton().disabled).toBe(false);
    expect(assemblySelect().disabled).toBe(false);
  });

  it('disables the assembly selector while the registry is being uploaded or removed', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');

    const uploading = deferred();
    backend.queue.registryUpload.push(uploading.promise);
    uploadRegistry();
    await waitFor(() => expect(assemblySelect().disabled).toBe(true));
    expect(registryInput().disabled).toBe(true);

    await act(async () =>
      uploading.resolve(
        jsonResponse({
          status: 'success',
          registry: REGISTRY('reg-rev-1', 'digest-1', 2),
          reused: false,
        }),
      ),
    );
    await waitFor(() => expect(assemblySelect().disabled).toBe(false));

    const removing = deferred();
    backend.queue.registryDelete.push(removing.promise);
    fireEvent.click(removeButton());
    await waitFor(() => expect(assemblySelect().disabled).toBe(true));

    await act(async () =>
      removing.resolve(jsonResponse({ status: 'success', cleared: true, registry: null })),
    );
    await waitFor(() => expect(assemblySelect().disabled).toBe(false));
  });

  it('keeps the existing registry when a replacement upload fails at the network layer', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());

    backend.queue.registryUpload.push(Promise.reject(new TypeError('Failed to fetch')));
    uploadRegistry('offline.tsv');

    await waitFor(() => expect(screen.getByText(/Network error uploading/i)).toBeTruthy());
    expect(screen.getByText('reg-rev-1')).toBeTruthy();
    expect(backend.calls.registryUploads).toHaveLength(2);
    expect(backend.calls.registryClears).toEqual([]);
  });

  it('clears the stale registry when execution reports session_expired', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry();
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    await loadBoth();

    backend.queue.execute.push(
      Promise.resolve(
        errorResponse(409, {
          code: 'session_expired',
          message: 'the session expired before the run committed',
          stale: ['registry'],
        }),
      ),
    );
    fireEvent.click(runButton());

    await waitFor(() => expect(screen.getByText(/session expired/i)).toBeTruthy());
    expect(screen.queryByText('reg-rev-1')).toBeNull();
    expect(runButton().disabled).toBe(true);
    expect(screen.getByText('q.bed')).toBeTruthy();
    expect(screen.getByText('a.bed')).toBeTruthy();
  });

  it('keeps the existing mapping and its result when a replacement is refused', async () => {
    const backend = registryBackend();
    await renderApp();
    chooseChromosomeSource();
    chooseNaming('UCSC names');
    uploadRegistry('one.tsv');
    await waitFor(() => expect(screen.getByText('reg-rev-1')).toBeTruthy());
    await loadBoth();
    await runOnce();

    backend.queue.registryUpload.push(
      Promise.resolve(
        errorResponse(400, {
          code: 'invalid_mapping',
          message: 'invalid custom chromosome mapping: duplicate sequence',
          stale: [],
          issues: [{ code: 'duplicate', message: 'row 2 duplicates row 1', rows: [2], columns: [] }],
          more: 0,
        }),
      ),
    );
    uploadRegistry('bad-replacement.tsv');

    await waitFor(() => expect(screen.getByText(/duplicate sequence/i)).toBeTruthy());
    const panel = screen.getByLabelText('Custom chromosome mapping registry');
    expect(within(panel).getByText('reg-rev-1')).toBeTruthy();
    expect(screen.getByText(/executed in/i)).toBeTruthy();
    expect(backend.calls.registryClears).toEqual([]);
  });
});
