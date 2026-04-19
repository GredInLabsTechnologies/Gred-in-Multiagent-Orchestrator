import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AgentPlanPanel } from '../AgentPlanPanel';
import { AgentPlan } from '../../types';

describe('AgentPlanPanel', () => {
    const mockPlan: AgentPlan = {
        id: 'p1',
        tasks: [
            { id: 't1', description: 'Task Done', status: 'done', output: 'Output 1' },
            { id: 't2', description: 'Task Running', status: 'running' },
            { id: 't3', description: 'Task Pending', status: 'pending' },
        ],
        reasoning: [
            { id: 'r1', content: 'Thought 1' },
            { id: 'r2', content: 'Thought 2' }
        ]
    };

    it('renders empty state when no plan is provided', () => {
        render(<AgentPlanPanel />);
        expect(screen.getByText(/No active plan/i)).toBeInTheDocument();
    });

    it('renders task list when plan is provided', () => {
        render(<AgentPlanPanel plan={mockPlan} />);
        expect(screen.getByText('Task Done')).toBeInTheDocument();
        expect(screen.getByText('Task Running')).toBeInTheDocument();
        expect(screen.getByText('Task Pending')).toBeInTheDocument();
        expect(screen.getByText('STEP 1')).toBeInTheDocument();
    });

    it('displays task output when available', () => {
        render(<AgentPlanPanel plan={mockPlan} />);
        expect(screen.getByText('Output 1')).toBeInTheDocument();
    });

    it('renders reasoning thoughts', () => {
        render(<AgentPlanPanel plan={mockPlan} />);
        expect(screen.getByText('Thought 1')).toBeInTheDocument();
        expect(screen.getByText('Thought 2')).toBeInTheDocument();
    });

    it('shows ACTIVE badge for running tasks', () => {
        render(<AgentPlanPanel plan={mockPlan} />);
        expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    });

    it('renders action buttons', () => {
        render(<AgentPlanPanel plan={mockPlan} />);
        expect(screen.getByRole('button', { name: /Pause Agent/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Cancel Plan/i })).toBeInTheDocument();
    });
});
