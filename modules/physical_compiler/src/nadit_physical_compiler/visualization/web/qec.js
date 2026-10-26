/* Static stabilizer supports, bound to the replay's moving atom identities. */
(function (root) {
  'use strict';
  const COLORS = {X: '#3966c6', Z: '#c26923', D: '#697886'};
  class Overlay {
    constructor(record) {
      this.checks = record?.checks || [];
      this.data = record?.data || [];
      this.title = record?.title || 'QEC structure';
    }
    scene(atoms, options = {}) {
      const visible = {X: true, Z: true, links: true, ...options};
      const markers = [], edges = [], data = new Set();
      for (const check of this.checks) {
        if (!visible[check.basis]) continue;
        const ancilla = atoms.get(check.ancilla);
        if (!ancilla) continue;
        markers.push({atom: ancilla, label: check.id, basis: check.basis});
        for (const id of check.data) {
          const target = atoms.get(id);
          if (!target) continue;
          data.add(id);
          if (visible.links) edges.push({from: ancilla, to: target, basis: check.basis, check: check.id});
        }
      }
      for (const item of this.data) {
        const atom = atoms.get(item.atom);
        if (atom && data.has(item.atom)) markers.push({atom, label: 'q' + item.qubit, basis: 'D'});
      }
      return {markers, edges};
    }
    describe(atom) {
      const check = this.checks.find(item => item.ancilla === atom);
      if (check) return [
        ['QEC role', check.basis + ' check ' + check.id],
        ['Stabilizer', check.data_qubits.map(q => check.basis + '(q' + q + ')').join(' ')],
      ];
      if (this.data.some(item => item.atom === atom)) return [
        ['QEC role', 'Data qubit'],
        ['Checks', this.checks.filter(item => item.data.includes(atom)).map(item => item.id).join(', ')],
      ];
      return [];
    }
  }
  const api = {Overlay, COLORS};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.AtomReplayQEC = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
