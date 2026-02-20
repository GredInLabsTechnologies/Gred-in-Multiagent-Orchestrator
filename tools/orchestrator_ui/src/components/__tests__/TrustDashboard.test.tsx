import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TrustDashboard } from '../security/TrustDashboard';
import { TrustRecord } from '../../hooks/useSecurityService';

const mockRecords: TrustRecord[] = [
    {
        dimension_key: 'planner',
        approvals: 10,
        rejections: 1,
        failures: 0,
        auto_approvals: 5,
        streak: 5,
        score: 0.95,
        policy: 'auto_approve',
        circuit_state: 'closed',
        circuit_opened_at: null,
        last_updated: '2023-01-01T00:00:00Z'
    },
    {
        dimension_key: 'coder',
        approvals: 5,
        rejections: 2,
        failures: 1,
        auto_approvals: 0,
        streak: 0,
        score: 0.60,
        policy: 'require_review',
        circuit_state: 'half_open',
        circuit_opened_at: '2023-01-01T00:00:00Z',
        last_updated: '2023-01-01T00:00:00Z'
    },
    {
        dimension_key: 'executor',
        approvals: 0,
        rejections: 5,
        failures: 3,
        auto_approvals: 0,
        streak: 0,
        score: 0.20,
        policy: 'blocked',
        circuit_state: 'open',
        circuit_opened_at: '2023-01-01T00:00:00Z',
        last_updated: '2023-01-01T00:00:00Z'
    }
];

describe('TrustDashboard', () => {
    it('renders empty state correctly', () => {
        render(<TrustDashboard records={[]} />);
        expect(screen.getByText('No trust records found.')).toBeInTheDocument();
    });

    it('renders records correctly', () => {
        render(<TrustDashboard records={mockRecords} />);

        // Check dimensions
        expect(screen.getByText('planner')).toBeInTheDocument();
        expect(screen.getByText('coder')).toBeInTheDocument();
        expect(screen.getByText('executor')).toBeInTheDocument();

        // Check scores (rounded)
        expect(screen.getByText('95%')).toBeInTheDocument();
        expect(screen.getByText('60%')).toBeInTheDocument();
        expect(screen.getByText('20%')).toBeInTheDocument();

        // Check policies
        expect(screen.getByText('AUTO APPROVE')).toBeInTheDocument();
        expect(screen.getByText('REQUIRE REVIEW')).toBeInTheDocument();
        expect(screen.getByText('BLOCKED')).toBeInTheDocument();

        // Check that failure counts render (use getAllByText since numbers appear in multiple columns)
        const ones = screen.getAllByText('1');
        expect(ones.length).toBeGreaterThanOrEqual(1); // coder has 1 failure
        const threes = screen.getAllByText('3');
        expect(threes.length).toBeGreaterThanOrEqual(1); // executor has 3 failures
    });
});
