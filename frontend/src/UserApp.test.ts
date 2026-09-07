import {describe,it,expect} from 'vitest';
import {creditLabel,stateLabel} from './UserApp';
describe('user credit display',()=>{
  it('shows user credits while keeping the internal ledger unit hidden',()=>{expect(creditLabel('0.050000')).toBe('5.00 créditos');expect(creditLabel('0.010000')).toBe('1.00 créditos');});
  it('describes a persisted request state without implying an answer exists',()=>{expect(stateLabel('RECEIVED')).toBe('Recibida');expect(stateLabel('TICKETED')).toBe('Completada');expect(stateLabel('FAILED')).toBe('No se pudo completar');});
});
