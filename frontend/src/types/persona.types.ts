export type TARSMode = 'attend' | 'task';

export interface TARSConfigResponse {
  mode: TARSMode | string;
}

export interface TARSConfigUpdateRequest {
  mode?: 'attend' | 'task' | 'companion' | 'work';
}

export interface PersonaDefinition {
  id: string;
  name: string;
  title: string;
  role: string;
  avatar?: string | null;
  speech_style: string;
  relationship_stance: string;
  allowed_tools: string[];
  is_builtin: boolean;
}
