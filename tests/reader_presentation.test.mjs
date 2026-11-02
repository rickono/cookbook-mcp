import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const script = readFileSync(new URL('../src/cookbook/reader_presentation.js', import.meta.url), 'utf8');

test('explicit text return focuses the reading anchor', () => {
  let focused = false;
  vm.runInNewContext(script, {
    document: {querySelector: () => ({focus() {focused = true;}})},
    location: {hash: '#text'},
  });
  assert.equal(focused, true);
});

test('ordinary navigation preserves focus', () => {
  let focused = false;
  vm.runInNewContext(script, {
    document: {querySelector: () => ({focus() {focused = true;}})},
    location: {hash: ''},
  });
  assert.equal(focused, false);
});
