import { beforeAll, afterEach, describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup, act } from '@testing-library/react';
import App from './App.jsx';

// recharts' ResponsiveContainer relies on ResizeObserver, which jsdom does
// not provide; a no-op observer is enough for rendering assertions.
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

const jsonResponse = (payload) => ({
  ok: true,
  status: 200,
  json: async () => payload,
});

const META = {
  version: '9.9.9-test',
  default_engine: 'polars-bio',
  assemblies: [],
  naming_options: [
    { key: 'UCSC-style', label: 'UCSC-style (chr1, chrX, chrM)' },
    { key: 'Ensembl-style', label: 'Ensembl-style (1, X, MT)' },
    { key: 'Keep original names', label: 'Keep original names' },
  ],
};

const dataset = (filename, format, totalRows, revision) => ({
  filename,
  format,
  total_rows: totalRows,
  columns: ['chr', 'start', 'end'],
  preview: [{ chr: 'chr1', start: 9, end: 20 }],
  needs_mapping: false,
  // Every stored dataset the server returns carries a revision; issue #51
  // makes the frontend clear only a revision it was given.
  ...(revision ? { revision } : {}),
});

const SAMPLE = {
  query: dataset('sample-query.bed', 'bed', 20, 'sample-query-rev'),
  annot: dataset('sample-annotation.gff3', 'gff3', 40, 'sample-annot-rev'),
};

const EXEC_RESULT = {
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
  preview: [
    { chr: 'chr1', start: 10, end: 20, has_overlap: true, gene_id: 'BRCA1' },
    { chr: 'chr2', start: 100, end: 150, has_overlap: false, gene_id: null },
  ],
  charts: {
    chromosome_distribution: [
      { chromosome: 'chr1', intervals: 12 },
      { chromosome: 'chr2', intervals: 8 },
    ],
    match_ratio: [
      { name: 'Matched', value: 12 },
      { name: 'Unmatched', value: 8 },
    ],
  },
};

// The two coordinate-system selects (query + annotation) are the only
// comboboxes whose first option is the 'Auto-detect' placeholder; DOM order
// puts the query select first.
const coordSelects = () =>
  screen.getAllByRole('combobox').filter(
    (s) => s.options.length === 3 && s.options[0].value === 'Auto-detect',
  );

const loadSample = async () => {
  fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
  await waitFor(() => expect(screen.getByText('sample-query.bed')).toBeTruthy());
  await waitFor(() => expect(screen.getByText('sample-annotation.gff3')).toBeTruthy());
};

describe('N2: the coordinate-system declaration is baked in at upload time', () => {
  it('changing the query coordinate system clears the dataset locally and server-side', async () => {
    const clearBodies = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url, options) => {
        const u = String(url);
        if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
        if (u === '/api/upload') {
          return Promise.resolve(jsonResponse(dataset('q.tsv', 'bed', 2, 'query-rev-1')));
        }
        if (u === '/api/dataset/clear') {
          clearBodies.push(options?.body);
          return Promise.resolve(
            jsonResponse({ status: 'success', cleared: 'query', was_loaded: true }),
          );
        }
        return Promise.resolve(jsonResponse({}));
      }),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText('v9.9.9-test')).toBeTruthy());

    const file = new File(['chr1\t10\t20\nchr2\t100\t150\n'], 'q.tsv', {
      type: 'text/tab-separated-values',
    });
    const fileInputs = document.querySelectorAll('input[type="file"]');
    expect(fileInputs).toHaveLength(2);
    fireEvent.change(fileInputs[0], { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText('q.tsv')).toBeTruthy());

    expect(coordSelects()).toHaveLength(2);
    fireEvent.change(coordSelects()[0], { target: { value: '1-based (GFF/GTF/VCF)' } });

    // The parsed dataset no longer belongs to the new declaration: the local
    // card is cleared and a re-upload is demanded.
    await waitFor(() => expect(screen.queryByText('q.tsv')).toBeNull());
    expect(screen.getByText(/re-upload the query file/i)).toBeTruthy();

    // The server-side copy is invalidated with the role and the exact
    // revision this tab loaded (issue #51: never a revision-less clear).
    expect(clearBodies).toEqual([
      JSON.stringify({ role: 'query', revision: 'query-rev-1' }),
    ]);
  });

  it('leaves the annot side untouched when the query declaration changes', async () => {
    const clearBodies = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url, options) => {
        const u = String(url);
        if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
        if (u === '/api/upload') {
          // Alternate responses by the role field in the form body.
          const role = String(options?.body?.get?.('role') ?? '');
          return Promise.resolve(
            jsonResponse(
              role === 'annot'
                ? dataset('a.tsv', 'gff3', 3, 'annot-rev-1')
                : dataset('q.tsv', 'bed', 2, 'query-rev-1'),
            ),
          );
        }
        if (u === '/api/dataset/clear') {
          clearBodies.push(options?.body);
          return Promise.resolve(jsonResponse({ status: 'success', cleared: 'query', was_loaded: true }));
        }
        return Promise.resolve(jsonResponse({}));
      }),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText('v9.9.9-test')).toBeTruthy());

    const fileInputs = document.querySelectorAll('input[type="file"]');
    fireEvent.change(fileInputs[0], {
      target: { files: [new File(['chr1\t10\t20\n'], 'q.tsv')] },
    });
    fireEvent.change(fileInputs[1], {
      target: { files: [new File(['chr1\t10\t20\tgene\n'], 'a.tsv')] },
    });
    await waitFor(() => expect(screen.getByText('q.tsv')).toBeTruthy());
    await waitFor(() => expect(screen.getByText('a.tsv')).toBeTruthy());

    fireEvent.change(coordSelects()[0], { target: { value: '1-based (GFF/GTF/VCF)' } });

    await waitFor(() => expect(screen.queryByText('q.tsv')).toBeNull());
    // Only the query side was invalidated.
    expect(screen.getByText('a.tsv')).toBeTruthy();
    expect(clearBodies).toEqual([
      JSON.stringify({ role: 'query', revision: 'query-rev-1' }),
    ]);
  });
});

describe('N3: in-flight execute responses and execution locking', () => {
  it('locks inputs while a run is in flight, discards a stale response, and renders the fresh one', async () => {
    const executeResolvers = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url) => {
        const u = String(url);
        if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
        if (u === '/api/load-sample') return Promise.resolve(jsonResponse(SAMPLE));
        if (u === '/api/execute') {
          return new Promise((resolve) => executeResolvers.push(resolve));
        }
        return Promise.resolve(jsonResponse({}));
      }),
    );

    render(<App />);
    await loadSample();

    const runBtn = screen.getByRole('button', { name: 'Run annotation' });

    // Two clicks land before React re-renders (a fast double-click): both
    // pass the isExecuting guard, so two runs are in flight and the first
    // run's response is stale by the time it arrives.
    await act(async () => {
      runBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      runBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(executeResolvers).toHaveLength(2);

    // While a run is in flight, every input is locked.
    const runningBtn = screen.getByRole('button', { name: 'Running annotation...' });
    expect(runningBtn.disabled).toBe(true);
    expect(screen.getAllByRole('combobox').every((s) => s.disabled)).toBe(true);
    document.querySelectorAll('input[type="file"]').forEach((i) => expect(i.disabled).toBe(true));
    expect(screen.getByRole('button', { name: /load sample data/i }).disabled).toBe(true);

    // The stale (first) response arrives while the newer run is still in
    // flight: it must not render and must not end the in-flight state.
    await act(async () => {
      executeResolvers[0](
        jsonResponse({ ...EXEC_RESULT, stats: { ...EXEC_RESULT.stats, mode: 'overlap', elapsed_seconds: 9.9 } }),
      );
    });
    expect(screen.queryByText(/executed in/i)).toBeNull();
    expect(screen.getByText(/no results yet/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Running annotation...' }).disabled).toBe(true);

    // The fresh (second) response arrives and renders with its own stats.
    await act(async () => {
      executeResolvers[1](jsonResponse(EXEC_RESULT));
    });
    await waitFor(() => expect(screen.getByText(/executed in 0.42s via BEDTOOLS/i)).toBeTruthy());
    expect(screen.getByText('closest / left')).toBeTruthy();
    expect(screen.getByText('12 of 20 regions')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Run annotation' }).disabled).toBe(false);
  });
});
// ---------------------------------------------------------------------------
// N2-R: coordinate declaration vs. in-flight upload / mapping requests
// ---------------------------------------------------------------------------

const ONE_BASED = '1-based (GFF/GTF/VCF)';

// A fetch stub whose /api/upload and /api/apply-mapping requests stay pending
// until the test settles them, recording what was sent.
const pendingBackend = () => {
  const uploads = [];
  const mappings = [];
  const clears = [];
  const clearBodies = [];
  const fetchStub = vi.fn((url, options) => {
    const u = String(url);
    if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
    if (u === '/api/upload') {
      return new Promise((resolve, reject) => {
        uploads.push({
          role: options.body.get('role'),
          coordSystem: options.body.get('coord_system'),
          resolve,
          reject,
        });
      });
    }
    if (u === '/api/apply-mapping') {
      return new Promise((resolve, reject) => {
        mappings.push({ body: JSON.parse(options.body), resolve, reject });
      });
    }
    if (u === '/api/dataset/clear') {
      const body = JSON.parse(options.body);
      clears.push(body.role);
      clearBodies.push(body);
      return Promise.resolve(jsonResponse({ status: 'success' }));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal('fetch', fetchStub);
  return { uploads, mappings, clears, clearBodies };
};

const renderApp = async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText('v9.9.9-test')).toBeTruthy());
};

const fileInputs = () => document.querySelectorAll('input[type="file"]');

const chooseFile = (role, name) => {
  fireEvent.change(fileInputs()[role === 'query' ? 0 : 1], {
    target: { files: [new File(['chr1\t99\t100\n'], name)] },
  });
};

const runButton = () => screen.getByRole('button', { name: 'Run annotation' });

describe('N2-R: the coordinate declaration cannot drift from an in-flight upload or mapping', () => {
  it('locks the coordinate selectors, pickers, mapping and run while an upload is in flight', async () => {
    const backend = pendingBackend();
    await renderApp();

    chooseFile('annot', 'a.gff3');
    await waitFor(() => expect(backend.uploads).toHaveLength(1));
    expect(backend.uploads[0]).toMatchObject({ role: 'annot', coordSystem: 'Auto-detect' });

    coordSelects().forEach((s) => expect(s.disabled).toBe(true));
    fileInputs().forEach((i) => expect(i.disabled).toBe(true));
    expect(screen.getByRole('button', { name: /load sample data/i }).disabled).toBe(true);
    expect(runButton().disabled).toBe(true);

    await act(async () => backend.uploads[0].resolve(jsonResponse(dataset('a.gff3', 'gff3', 1))));
    await waitFor(() => expect(screen.getByText('a.gff3')).toBeTruthy());
    coordSelects().forEach((s) => expect(s.disabled).toBe(false));
    fileInputs().forEach((i) => expect(i.disabled).toBe(false));
  });

  it('first upload: a declaration change mid-flight discards the stale response on both ends', async () => {
    // The re-gate's S2: upload sent under "Auto-detect", selector switched to
    // 1-based while in flight. The stale table must not be shown as loaded
    // under the 1-based selector. fireEvent bypasses the `disabled` lock, so
    // this exercises the generation guard on its own.
    const backend = pendingBackend();
    await renderApp();

    chooseFile('query', 'q.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(1));
    expect(backend.uploads[0].coordSystem).toBe('Auto-detect');
    const pickerBefore = fileInputs()[0];

    fireEvent.change(coordSelects()[0], { target: { value: ONE_BASED } });
    await act(async () => backend.uploads[0].resolve(jsonResponse(dataset('q.bed', 'bed', 1, 'query-rev-1'))));

    await waitFor(() => expect(backend.clears).toEqual(['query']));
    // Issue #51: the superseded success is cleaned up by exactly the revision
    // it reported, never by a revision-less clear.
    expect(backend.clearBodies).toEqual([{ role: 'query', revision: 'query-rev-1' }]);
    expect(screen.queryByText('q.bed')).toBeNull();
    expect(coordSelects()[0].value).toBe(ONE_BASED);
    expect(screen.getByText(/changed while the query file was being processed/i)).toBeTruthy();
    // The picker is remounted so choosing the same file again re-uploads it.
    expect(fileInputs()[0]).not.toBe(pickerBefore);

    // Re-upload goes out under the declaration that is displayed.
    chooseFile('query', 'q.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(2));
    expect(backend.uploads[1].coordSystem).toBe(ONE_BASED);
    await act(async () => backend.uploads[1].resolve(jsonResponse(dataset('q.bed', 'bed', 1, 'query-rev-2'))));
    await waitFor(() => expect(screen.getByText('q.bed')).toBeTruthy());
  });

  it('re-upload / slow parse: a stale response cannot restore the invalidated dataset', async () => {
    // The re-gate's S3/S4: the invalidation clear fires, then the slow
    // in-flight re-upload response arrives and used to repopulate the card
    // with the old declaration while the server copy had been cleared.
    const backend = pendingBackend();
    await renderApp();

    chooseFile('query', 'old.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(1));
    await act(async () => backend.uploads[0].resolve(jsonResponse(dataset('old.bed', 'bed', 1, 'query-rev-1'))));
    await waitFor(() => expect(screen.getByText('old.bed')).toBeTruthy());

    chooseFile('query', 'new.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(2));
    fireEvent.change(coordSelects()[0], { target: { value: ONE_BASED } });
    await waitFor(() => expect(backend.clears).toEqual(['query']));
    expect(screen.queryByText('old.bed')).toBeNull();

    await act(async () => backend.uploads[1].resolve(jsonResponse(dataset('new.bed', 'bed', 1, 'query-rev-2'))));
    // The stale response is discarded, and the copy the server may have
    // stored after the first clear is cleared again -- each by its own
    // revision (issue #51).
    await waitFor(() => expect(backend.clears).toEqual(['query', 'query']));
    expect(backend.clearBodies).toEqual([
      { role: 'query', revision: 'query-rev-1' },
      { role: 'query', revision: 'query-rev-2' },
    ]);
    expect(screen.queryByText('new.bed')).toBeNull();
    expect(screen.queryByText('old.bed')).toBeNull();
    expect(coordSelects()[0].disabled).toBe(false);
  });

  it('tracks query and annotation independently', async () => {
    const backend = pendingBackend();
    await renderApp();

    // An annotation upload is in flight when the *query* declaration changes:
    // the annotation response is still current and lands.
    chooseFile('annot', 'a.gff3');
    await waitFor(() => expect(backend.uploads).toHaveLength(1));
    fireEvent.change(coordSelects()[0], { target: { value: ONE_BASED } });
    await act(async () => backend.uploads[0].resolve(jsonResponse(dataset('a.gff3', 'gff3', 1, 'annot-rev-1'))));
    await waitFor(() => expect(screen.getByText('a.gff3')).toBeTruthy());
    expect(backend.clears).toEqual([]);

    // A query upload in flight when the *annotation* declaration changes:
    // the query lands, the loaded annotation is the one invalidated.
    chooseFile('query', 'q.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(2));
    expect(backend.uploads[1].coordSystem).toBe(ONE_BASED);
    fireEvent.change(coordSelects()[1], { target: { value: ONE_BASED } });
    await act(async () => backend.uploads[1].resolve(jsonResponse(dataset('q.bed', 'bed', 1, 'query-rev-2'))));
    await waitFor(() => expect(screen.getByText('q.bed')).toBeTruthy());
    expect(screen.queryByText('a.gff3')).toBeNull();
    expect(backend.clears).toEqual(['annot']);
    expect(backend.clearBodies).toEqual([{ role: 'annot', revision: 'annot-rev-1' }]);
  });

  it('mapping: locks the selectors while in flight and a stale mapping cannot resurrect the query', async () => {
    const backend = pendingBackend();
    await renderApp();

    chooseFile('query', 'custom.tsv');
    await waitFor(() => expect(backend.uploads).toHaveLength(1));
    await act(async () =>
      backend.uploads[0].resolve(
        jsonResponse({
          ...dataset('custom.tsv', 'custom', 1, 'query-rev-1'),
          columns: ['c', 'p', 'e'],
          needs_mapping: true,
        }),
      ),
    );
    await waitFor(() => expect(screen.getByText(/column mapping required/i)).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Apply Mapping' }));
    await waitFor(() => expect(backend.mappings).toHaveLength(1));
    expect(backend.mappings[0].body.coord_system).toBe('Auto-detect');
    coordSelects().forEach((s) => expect(s.disabled).toBe(true));
    expect(screen.getByRole('button', { name: 'Apply Mapping' }).disabled).toBe(true);
    fileInputs().forEach((i) => expect(i.disabled).toBe(true));

    fireEvent.change(coordSelects()[0], { target: { value: ONE_BASED } });
    await waitFor(() => expect(backend.clears).toEqual(['query']));
    await act(async () =>
      backend.mappings[0].resolve(jsonResponse({
        revision: 'mapped-rev-2', total_rows: 1, columns: ['chr', 'start', 'end'], preview: [],
      })),
    );
    await waitFor(() => expect(backend.clears).toEqual(['query', 'query']));
    expect(backend.clearBodies).toEqual([
      { role: 'query', revision: 'query-rev-1' },
      { role: 'query', revision: 'mapped-rev-2' },
    ]);
    expect(screen.queryByText('custom.tsv')).toBeNull();
    expect(screen.queryByText(/column mapping applied/i)).toBeNull();
    expect(screen.queryByText(/✓/)).toBeNull();
    coordSelects().forEach((s) => expect(s.disabled).toBe(false));
  });

  it('keeps client and server consistent when an upload fails', async () => {
    const backend = pendingBackend();
    await renderApp();

    chooseFile('query', 'q.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(1));
    await act(async () => backend.uploads[0].resolve(jsonResponse(dataset('q.bed', 'bed', 1, 'query-rev-1'))));
    await waitFor(() => expect(screen.getByText('q.bed')).toBeTruthy());

    // A rejected upload (the server stores nothing) keeps the loaded file on
    // both ends.
    chooseFile('query', 'bad.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(2));
    await act(async () =>
      backend.uploads[1].resolve({ ok: false, status: 400, json: async () => ({ detail: 'bad file' }) }),
    );
    await waitFor(() => expect(screen.getByText('bad file')).toBeTruthy());
    expect(screen.getByText('q.bed')).toBeTruthy();
    expect(backend.clears).toEqual([]);

    // A network failure leaves the server outcome unknown: the side is
    // dropped on both ends instead of showing a file the server may not hold.
    // The clear names the last revision this tab owned (issue #51), so it can
    // only ever remove that revision, never a newer one.
    chooseFile('query', 'net.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    await act(async () => backend.uploads[2].reject(new TypeError('network down')));
    await waitFor(() => expect(backend.clears).toEqual(['query']));
    expect(backend.clearBodies).toEqual([{ role: 'query', revision: 'query-rev-1' }]);
    expect(screen.queryByText('q.bed')).toBeNull();
    expect(screen.queryByText('net.bed')).toBeNull();
    expect(coordSelects()[0].disabled).toBe(false);
  });
});

describe('N7: annotation-side coordinate declaration', () => {
  it('changing the annotation coordinate system invalidates only the annotation dataset', async () => {
    const backend = pendingBackend();
    await renderApp();

    chooseFile('query', 'q.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(1));
    await act(async () => backend.uploads[0].resolve(jsonResponse(dataset('q.bed', 'bed', 2, 'query-rev-1'))));
    chooseFile('annot', 'a.gff3');
    await waitFor(() => expect(backend.uploads).toHaveLength(2));
    await act(async () => backend.uploads[1].resolve(jsonResponse(dataset('a.gff3', 'gff3', 3, 'annot-rev-2'))));
    await waitFor(() => expect(screen.getByText('a.gff3')).toBeTruthy());
    expect(screen.getByText('q.bed')).toBeTruthy();
    const annotPickerBefore = fileInputs()[1];
    const queryPickerBefore = fileInputs()[0];

    fireEvent.change(coordSelects()[1], { target: { value: ONE_BASED } });

    await waitFor(() => expect(screen.queryByText('a.gff3')).toBeNull());
    expect(screen.getByText(/re-upload the annot file/i)).toBeTruthy();
    expect(backend.clears).toEqual(['annot']);
    expect(backend.clearBodies).toEqual([{ role: 'annot', revision: 'annot-rev-2' }]);
    // The query dataset, its picker and its declaration are untouched.
    expect(screen.getByText('q.bed')).toBeTruthy();
    expect(fileInputs()[0]).toBe(queryPickerBefore);
    expect(fileInputs()[1]).not.toBe(annotPickerBefore);
    expect(coordSelects()[0].value).toBe('Auto-detect');

    // The annotation re-upload carries the new declaration.
    chooseFile('annot', 'a.gff3');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    expect(backend.uploads[2]).toMatchObject({ role: 'annot', coordSystem: ONE_BASED });
  });
});

// ---------------------------------------------------------------------------
// F1: tabs of one browser share the server session; revisions bind each tab
// to the datasets and result it displays.
// ---------------------------------------------------------------------------

const CONFLICT = (stale, message) => ({
  ok: false,
  status: 409,
  json: async () => ({ detail: { code: 'revision_conflict', stale, message } }),
});

// A backend issuing revisions, recording what the tab sends; `next` lets a
// test script the response of the next call to an endpoint.
const revisionBackend = () => {
  const sent = { execute: [], mapping: [], exports: [], clears: [] };
  const next = {};
  let counter = 0;
  const rev = (tag) => `${tag}-rev-${++counter}`;
  const fetchStub = vi.fn((url, options) => {
    const u = String(url);
    const scripted = next[u.split('?')[0]];
    if (scripted) {
      delete next[u.split('?')[0]];
      if (u.startsWith('/api/export/')) sent.exports.push(u);
      return Promise.resolve(scripted);
    }
    if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
    if (u === '/api/upload') {
      const role = options.body.get('role');
      const name = options.body.get('file').name;
      const mapping = name.endsWith('.csv');
      return Promise.resolve(jsonResponse({
        ...dataset(name, mapping ? 'custom' : 'bed', 1),
        ...(mapping ? { columns: ['c', 'p', 'e'], needs_mapping: true } : {}),
        role,
        revision: rev(role),
      }));
    }
    if (u === '/api/apply-mapping') {
      sent.mapping.push(JSON.parse(options.body));
      return Promise.resolve(jsonResponse({
        revision: rev('mapped'), total_rows: 1, columns: ['chr', 'start', 'end'], preview: [],
      }));
    }
    if (u === '/api/execute') {
      const body = JSON.parse(options.body);
      sent.execute.push(body);
      return Promise.resolve(jsonResponse({
        ...EXEC_RESULT,
        result_revision: rev('result'),
        query_revision: body.query_rev,
        annot_revision: body.annot_rev,
      }));
    }
    if (u.startsWith('/api/export/')) {
      sent.exports.push(u);
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: () => 'attachment; filename=annotated_intervals.csv' },
        blob: async () => new Blob(['chr,start\n']),
      });
    }
    if (u === '/api/dataset/clear') {
      sent.clears.push(JSON.parse(options.body));
      return Promise.resolve(jsonResponse({ status: 'success' }));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal('fetch', fetchStub);
  return { sent, next };
};

// jsdom has no object URLs; record downloads instead.
const stubObjectUrls = () => {
  const createObjectURL = vi.fn(() => 'blob:export');
  URL.createObjectURL = createObjectURL;
  URL.revokeObjectURL = vi.fn();
  return createObjectURL;
};

afterEach(() => {
  delete URL.createObjectURL;
  delete URL.revokeObjectURL;
});

const uploadBoth = async () => {
  chooseFile('query', 'q.bed');
  await waitFor(() => expect(screen.getByText('q.bed')).toBeTruthy());
  chooseFile('annot', 'a.bed');
  await waitFor(() => expect(screen.getByText('a.bed')).toBeTruthy());
};

const runOnce = async () => {
  fireEvent.click(runButton());
  await waitFor(() => expect(screen.getByText(/executed in/i)).toBeTruthy());
};

describe('F1: one tab never runs on, shows or exports another tab’s state', () => {
  it('executes with the dataset revisions this tab displays, including after mapping', async () => {
    const { sent } = revisionBackend();
    await renderApp();
    chooseFile('query', 'custom.csv');
    await waitFor(() => expect(screen.getByText(/column mapping required/i)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Apply Mapping' }));
    await waitFor(() => expect(screen.getByText(/column mapping applied/i)).toBeTruthy());
    expect(sent.mapping[0].query_rev).toBe('query-rev-1');
    chooseFile('annot', 'a.bed');
    await waitFor(() => expect(screen.getByText('a.bed')).toBeTruthy());

    await runOnce();
    expect(sent.execute[0]).toMatchObject({ query_rev: 'mapped-rev-2', annot_rev: 'annot-rev-3' });
  });

  it('a 409 on execute visibly reports the other tab and drops the stale side', async () => {
    const { next } = revisionBackend();
    await renderApp();
    await uploadBoth();

    next['/api/execute'] = CONFLICT(['query'], 'The query dataset shown in this tab is no longer the one loaded (replaced in another tab).');
    fireEvent.click(runButton());

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/changed in another tab/i);
    expect(alert.textContent).toMatch(/replaced in another tab/i);
    expect(screen.queryByText('q.bed')).toBeNull();
    expect(screen.getByText('a.bed')).toBeTruthy();
    expect(screen.getByText(/no results yet/i)).toBeTruthy();
    expect(runButton().disabled).toBe(true);
  });

  it('exports name the displayed result revision and download it', async () => {
    const { sent } = revisionBackend();
    const createObjectURL = stubObjectUrls();
    await renderApp();
    await uploadBoth();
    await runOnce();

    fireEvent.click(screen.getByRole('button', { name: /^CSV$/ }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    const exported = new URL(sent.exports[0], 'http://x');
    expect(exported.pathname).toBe('/api/export/csv');
    expect(exported.searchParams.get('result_rev')).toBe('result-rev-3');
    expect(exported.searchParams.get('filter_type')).toBe('all');
  });

  it('an export after another tab ran is a visible conflict, never a download', async () => {
    const { sent, next } = revisionBackend();
    const createObjectURL = stubObjectUrls();
    await renderApp();
    await uploadBoth();
    await runOnce();

    next['/api/export/csv'] = CONFLICT(['result'], 'The results shown in this tab were replaced by another tab. Nothing was exported.');
    fireEvent.click(screen.getByRole('button', { name: /^CSV$/ }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/changed in another tab/i);
    expect(alert.textContent).toMatch(/nothing was exported/i);
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(sent.exports).toHaveLength(1);
    // The superseded results are no longer presented as this tab's.
    expect(screen.getByText(/no results yet/i)).toBeTruthy();
    // The tab's own datasets are still its own: it can simply re-run.
    expect(screen.getByText('q.bed')).toBeTruthy();
    expect(runButton().disabled).toBe(false);
  });

  it('invalidating a side clears only the revision this tab loaded', async () => {
    const { sent } = revisionBackend();
    await renderApp();
    await uploadBoth();
    fireEvent.change(coordSelects()[1], { target: { value: ONE_BASED } });
    await waitFor(() => expect(sent.clears).toHaveLength(1));
    expect(sent.clears[0]).toEqual({ role: 'annot', revision: 'annot-rev-2' });
  });
});

// ---------------------------------------------------------------------------
// #58: upload and sample-load revision conflicts must drop the stale side
// (reset it, clear results, show the warning, disable Run), not merely show an
// error and keep the superseded dataset displayed with Run enabled.
// ---------------------------------------------------------------------------

// A backend whose upload and sample-load responses stay pending until a test
// settles them, so a request can be superseded before its response lands. Each
// upload carries the revision the frontend would echo back on success.
const conflictBackend = () => {
  const uploads = [];
  const samples = [];
  const clears = [];
  let counter = 0;
  const uploadResponse = (name, role) => ({
    ...dataset(name, 'bed', 1),
    role,
    revision: `${role}-rev-${++counter}`,
  });
  const fetchStub = vi.fn((url, options) => {
    const u = String(url);
    if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
    if (u === '/api/upload') {
      return new Promise((resolve, reject) => {
        uploads.push({
          role: options.body.get('role'),
          name: options.body.get('file').name,
          resolve,
          reject,
        });
      });
    }
    if (u === '/api/load-sample') {
      return new Promise((resolve, reject) => samples.push({ resolve, reject }));
    }
    if (u === '/api/dataset/clear') {
      clears.push(JSON.parse(options.body));
      return Promise.resolve(jsonResponse({ status: 'success' }));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal('fetch', fetchStub);
  return { uploads, samples, clears, uploadResponse };
};

// Load both sides through the conflict backend, settling each upload in order.
const loadBoth = async (backend) => {
  chooseFile('query', 'q.bed');
  await waitFor(() => expect(backend.uploads).toHaveLength(1));
  chooseFile('annot', 'a.bed');
  await waitFor(() => expect(backend.uploads).toHaveLength(2));
  await act(async () => backend.uploads[0].resolve(jsonResponse(backend.uploadResponse('q.bed', 'query'))));
  await act(async () => backend.uploads[1].resolve(jsonResponse(backend.uploadResponse('a.bed', 'annot'))));
  await waitFor(() => expect(screen.getByText('q.bed')).toBeTruthy());
  await waitFor(() => expect(screen.getByText('a.bed')).toBeTruthy());
};

describe('#58: upload / sample-load revision conflicts drop the stale side', () => {
  it('an upload 409 clears the stale query side and preserves the annotation', async () => {
    const backend = conflictBackend();
    await renderApp();
    await loadBoth(backend);

    chooseFile('query', 'q2.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    await act(async () =>
      backend.uploads[2].resolve(
        CONFLICT(['query'], 'This query upload was superseded by a newer upload or clear from another tab of this browser session; nothing was stored.'),
      ),
    );

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/changed in another tab/i);
    expect(screen.queryByText('q.bed')).toBeNull();
    expect(screen.queryByText('q2.bed')).toBeNull();
    expect(screen.getByText('a.bed')).toBeTruthy();
    expect(runButton().disabled).toBe(true);
    expect(backend.clears).toEqual([]);
  });

  it('an annotation 409 clears the stale annotation side and preserves the query', async () => {
    const backend = conflictBackend();
    await renderApp();
    await loadBoth(backend);

    chooseFile('annot', 'a2.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    await act(async () =>
      backend.uploads[2].resolve(
        CONFLICT(['annot'], 'This annot upload was superseded by a newer upload or clear from another tab of this browser session; nothing was stored.'),
      ),
    );

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/changed in another tab/i);
    expect(screen.queryByText('a.bed')).toBeNull();
    expect(screen.queryByText('a2.bed')).toBeNull();
    expect(screen.getByText('q.bed')).toBeTruthy();
    expect(runButton().disabled).toBe(true);
  });

  it('a sample-load 409 resets the stale sides and warns', async () => {
    const backend = conflictBackend();
    await renderApp();
    await loadBoth(backend);

    fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
    await waitFor(() => expect(backend.samples).toHaveLength(1));
    await act(async () =>
      backend.samples[0].resolve(
        CONFLICT(['query', 'annot'], 'This sample load was superseded by a newer upload or clear from another tab of this browser session; nothing was stored.'),
      ),
    );

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/changed in another tab/i);
    await waitFor(() => expect(screen.queryByText('q.bed')).toBeNull());
    expect(screen.queryByText('a.bed')).toBeNull();
    expect(runButton().disabled).toBe(true);
  });

  it('a superseded (stale) 409 response cannot tear down a newer dataset', async () => {
    const backend = conflictBackend();
    await renderApp();
    await loadBoth(backend);

    // Two query uploads: the first is slow, the second lands first.
    chooseFile('query', 'older.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    chooseFile('query', 'newer.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(4));

    await act(async () => backend.uploads[3].resolve(jsonResponse(backend.uploadResponse('newer.bed', 'query'))));
    await waitFor(() => expect(screen.getByText('newer.bed')).toBeTruthy());

    // The superseded request now arrives as a 409: it describes a request this
    // tab no longer owns, so it must be ignored, not tear down newer.bed.
    await act(async () =>
      backend.uploads[2].resolve(CONFLICT(['query'], 'superseded older upload')),
    );

    await waitFor(() => expect(screen.queryByText(/changed in another tab/i)).toBeNull());
    expect(screen.getByText('newer.bed')).toBeTruthy();
    expect(screen.queryByText('older.bed')).toBeNull();
    expect(runButton().disabled).toBe(false);
  });

  it('a superseded (stale) sample-load success cannot overwrite a newer query', async () => {
    const backend = conflictBackend();
    await renderApp();
    await loadBoth(backend);

    fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
    await waitFor(() => expect(backend.samples).toHaveLength(1));

    chooseFile('query', 'newer.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    await act(async () => backend.uploads[2].resolve(jsonResponse(backend.uploadResponse('newer.bed', 'query'))));
    await waitFor(() => expect(screen.getByText('newer.bed')).toBeTruthy());

    await act(async () => backend.samples[0].resolve(jsonResponse(SAMPLE)));

    expect(screen.queryByText('sample-query.bed')).toBeNull();
    expect(screen.getByText('newer.bed')).toBeTruthy();
  });

  it('sample-load success still populates both sides without a conflict', async () => {
    const backend = conflictBackend();
    await renderApp();

    fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
    await waitFor(() => expect(backend.samples).toHaveLength(1));
    await act(async () => backend.samples[0].resolve(jsonResponse(SAMPLE)));

    await waitFor(() => expect(screen.getByText('sample-query.bed')).toBeTruthy());
    expect(screen.getByText('sample-annotation.gff3')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(runButton().disabled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// #51 / #52: revision-safe cleanup. Every clear names a revision the tab owns,
// so an unknown-outcome or superseded request can never remove a newer dataset
// (here or in another tab of the same session). Guard-level tests: fireEvent
// bypasses the disabled controls on purpose to drive the request-generation
// guards; the opt-in real-browser suite (tests/test_browser_multi_tab.py)
// proves the same recovery through genuinely enabled controls.
// ---------------------------------------------------------------------------

describe('#51/#52: revision-safe cleanup never wipes a newer dataset', () => {
  it('an unknown-outcome upload error clears only the revision the tab owned', async () => {
    const backend = conflictBackend();
    await renderApp();
    await loadBoth(backend);

    chooseFile('query', 'net.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    await act(async () => backend.uploads[2].reject(new TypeError('network down')));

    await waitFor(() => expect(backend.clears).toHaveLength(1));
    // The clear names the last revision this tab owned, not the failed
    // request's unknown revision -- and never a revision-less fallback.
    expect(backend.clears[0]).toEqual({ role: 'query', revision: 'query-rev-1' });
    // The query is dropped locally; the untouched annotation survives.
    expect(screen.queryByText('q.bed')).toBeNull();
    expect(screen.getByText('a.bed')).toBeTruthy();
    expect(runButton().disabled).toBe(true);
  });

  it('an unknown-outcome upload error with nothing loaded sends no clear', async () => {
    const backend = conflictBackend();
    await renderApp();

    chooseFile('query', 'net.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(1));
    await act(async () => backend.uploads[0].reject(new TypeError('network down')));

    await waitFor(() => expect(screen.getByText(/Network error uploading file/i)).toBeTruthy());
    // No revision is known, so nothing is sent: the unknown server copy is
    // left for the next write, never guessed away (issue #51).
    expect(backend.clears).toEqual([]);
    expect(screen.queryByText('net.bed')).toBeNull();
  });

  it('a superseded successful upload is cleaned up by its own returned revision', async () => {
    const backend = conflictBackend();
    await renderApp();
    await loadBoth(backend);

    chooseFile('query', 'older.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    chooseFile('query', 'newer.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(4));

    const newer = backend.uploadResponse('newer.bed', 'query');
    await act(async () => backend.uploads[3].resolve(jsonResponse(newer)));
    await waitFor(() => expect(screen.getByText('newer.bed')).toBeTruthy());

    const older = backend.uploadResponse('older.bed', 'query');
    await act(async () => backend.uploads[2].resolve(jsonResponse(older)));

    await waitFor(() => expect(backend.clears).toHaveLength(1));
    expect(backend.clears[0]).toEqual({ role: 'query', revision: older.revision });
    // The newer dataset this tab now displays is not torn down.
    expect(screen.getByText('newer.bed')).toBeTruthy();
    expect(runButton().disabled).toBe(false);
  });

  it('a superseded failed upload never triggers an unconditional clear', async () => {
    const backend = conflictBackend();
    await renderApp();
    await loadBoth(backend);

    chooseFile('query', 'older.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    chooseFile('query', 'newer.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(4));

    await act(async () =>
      backend.uploads[3].resolve(jsonResponse(backend.uploadResponse('newer.bed', 'query'))),
    );
    await waitFor(() => expect(screen.getByText('newer.bed')).toBeTruthy());

    await act(async () =>
      backend.uploads[2].resolve({ ok: false, status: 400, json: async () => ({ detail: 'bad file' }) }),
    );

    expect(backend.clears).toEqual([]);
    expect(screen.getByText('newer.bed')).toBeTruthy();
    expect(runButton().disabled).toBe(false);
  });

  it('a superseded sample-load success clears only the revisions it returned', async () => {
    const backend = conflictBackend();
    await renderApp();
    await loadBoth(backend);

    fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
    await waitFor(() => expect(backend.samples).toHaveLength(1));

    chooseFile('query', 'newer.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    await act(async () =>
      backend.uploads[2].resolve(jsonResponse(backend.uploadResponse('newer.bed', 'query'))),
    );
    await waitFor(() => expect(screen.getByText('newer.bed')).toBeTruthy());

    await act(async () => backend.samples[0].resolve(jsonResponse(SAMPLE)));

    // Only the sample's own revisions are cleared; a query replaced in this
    // tab answers 409 server-side and the newer dataset survives.
    await waitFor(() =>
      expect(backend.clears).toEqual([
        { role: 'query', revision: 'sample-query-rev' },
        { role: 'annot', revision: 'sample-annot-rev' },
      ]),
    );
    expect(screen.queryByText('sample-query.bed')).toBeNull();
    expect(screen.getByText('newer.bed')).toBeTruthy();
  });

  it('a superseded sample-load network error keeps the newer dataset', async () => {
    const backend = conflictBackend();
    await renderApp();
    await loadBoth(backend);

    fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
    await waitFor(() => expect(backend.samples).toHaveLength(1));

    chooseFile('query', 'newer.bed');
    await waitFor(() => expect(backend.uploads).toHaveLength(3));
    await act(async () =>
      backend.uploads[2].resolve(jsonResponse(backend.uploadResponse('newer.bed', 'query'))),
    );
    await waitFor(() => expect(screen.getByText('newer.bed')).toBeTruthy());

    await act(async () => backend.samples[0].reject(new TypeError('network down')));

    // Superseded with an unknown outcome: no revision to name is this tab's
    // to clear, and neither side is torn down.
    expect(backend.clears).toEqual([]);
    expect(screen.getByText('newer.bed')).toBeTruthy();
    expect(runButton().disabled).toBe(false);
  });
});
