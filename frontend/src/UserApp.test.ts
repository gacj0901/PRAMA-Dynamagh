import {describe,it,expect} from 'vitest';
import {creditLabel,stateLabel} from './UserApp';
describe('user credit display',()=>{
  it('shows internal credit without a currency or network label',()=>{expect(creditLabel('0.250000')).toBe('0.25 créditos');expect(creditLabel('0.004000')).toBe('0.004 créditos');});
  it('describes a persisted request state without implying an answer exists',()=>{expect(stateLabel('RECEIVED')).toBe('Recibida');expect(stateLabel('TICKETED')).toBe('Completada');expect(stateLabel('FAILED')).toBe('No se pudo completar');});
});
