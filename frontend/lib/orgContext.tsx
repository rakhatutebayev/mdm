'use client';

import { createContext, useContext, useEffect, useState, ReactNode } from 'react';

export interface OrgOption {
    id: string;
    name: string;
    domain?: string;
}

interface OrgContextValue {
    orgs: OrgOption[];
    activeOrg: OrgOption | null;
    setActiveOrg: (org: OrgOption) => void;
    isSuperAdmin: boolean;
}

const OrgContext = createContext<OrgContextValue>({
    orgs: [],
    activeOrg: null,
    setActiveOrg: () => {},
    isSuperAdmin: false,
});

export function OrgProvider({ children }: { children: ReactNode }) {
    const [orgs, setOrgs] = useState<OrgOption[]>([]);
    const [activeOrg, setActiveOrgState] = useState<OrgOption | null>(null);
    const [isSuperAdmin, setIsSuperAdmin] = useState(false);

    useEffect(() => {
        const token = localStorage.getItem('access_token');
        if (!token) return;

        // Fetch current user to check role
        fetch('/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } })
            .then(r => r.json())
            .then(me => {
                const isSuper = me.role === 'super_admin';
                setIsSuperAdmin(isSuper);

                if (isSuper) {
                    // SUPER_ADMIN: load all orgs
                    fetch('/api/v1/organizations', { headers: { Authorization: `Bearer ${token}` } })
                        .then(r => r.json())
                        .then((list: OrgOption[]) => {
                            setOrgs(list);
                            // Restore previously selected org
                            const saved = localStorage.getItem('active_org_id');
                            const found = saved ? list.find(o => o.id === saved) : null;
                            setActiveOrgState(found || list[0] || null);
                        })
                        .catch(() => {});
                } else {
                    // Regular user: show only their org
                    if (me.org_id) {
                        const myOrg: OrgOption = { id: me.org_id, name: me.org_name || 'My Organization' };
                        setOrgs([myOrg]);
                        setActiveOrgState(myOrg);
                    }
                }
            })
            .catch(() => {});
    }, []);

    const setActiveOrg = (org: OrgOption) => {
        setActiveOrgState(org);
        localStorage.setItem('active_org_id', org.id);
        // Store in api.ts as header override
        localStorage.setItem('active_org_header', org.id);
        // Reload to re-fetch all data in context of new org
        window.location.reload();
    };

    return (
        <OrgContext.Provider value={{ orgs, activeOrg, setActiveOrg, isSuperAdmin }}>
            {children}
        </OrgContext.Provider>
    );
}

export const useOrg = () => useContext(OrgContext);
