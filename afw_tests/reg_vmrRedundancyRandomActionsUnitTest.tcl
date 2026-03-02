#!/usr/bin/env tclsh
#
# Standalone test for the chaotic-mode action list generation in
# reg_vmrRedundancyRandomActions.tcl.
#
# Runs the generation loop N times and validates each produced actionList
# for safety violations:
#   - no action may run on a powered-down target
#   - no action may run on an ungracefully-powered-down target
#
# Usage:
#   tclsh test_action_list_gen.tcl
#
# No router or AFW environment is required.  The script exits with status 0
# on success and 1 if any violations are found.
#

# ---------------------------------------------------------------------------
# Stub for the AFW list-shuffle helper
# ---------------------------------------------------------------------------
proc lshuffle {lst} {
    set n [llength $lst]
    for {set i [expr {$n - 1}]} {$i > 0} {incr i -1} {
        set j [expr {int(rand() * ($i + 1))}]
        set tmp  [lindex $lst $i]
        lset lst $i [lindex $lst $j]
        lset lst $j $tmp
    }
    return $lst
}

# ---------------------------------------------------------------------------
# Copied verbatim from reg_vmrRedundancyRandomActions.tcl
# ---------------------------------------------------------------------------
# Returns 1 if any action on any of the targets in targetList appears after
# startIndex in actionList before the given recoveryAction for that target.
proc HasActionOnTargetBeforeRecovery {actionList startIndex targetList recoveryAction} {
    foreach target [split $targetList -] {
        for {set fwd $startIndex} {$fwd < [llength $actionList]} {incr fwd} {
            set fwdItem    [lindex $actionList $fwd]
            set fwdAction  [lindex [split $fwdItem :] 0]
            set fwdTargets [split [lindex [split $fwdItem :] 1] -]
            if {[lsearch $fwdTargets $target] >= 0} {
                if {$fwdAction == $recoveryAction} {
                    break
                } else {
                    return 1
                }
            }
        }
    }
    return 0
}

# ---------------------------------------------------------------------------
# Validator: walk actionList sequentially and track power-state per node.
# Returns a list of human-readable violation strings (empty means clean).
# ---------------------------------------------------------------------------
proc ValidateActionList {actionList} {
    set allTargets {primary backup monitor}
    foreach t $allTargets {
        set pd($t)   0
        set ugpd($t) 0
    }
    set errors {}

    foreach item $actionList {
        set action  [lindex [split $item :] 0]
        set targets [split [lindex [split $item :] 1] -]

        # skip sleep/check pseudo-entries
        if {$action eq "sleep" || $action eq "check"} continue

        foreach t $targets {
            if {$t eq ""} continue
            if {$action eq "powerUp"} {
                # powerUp is the recovery for powerDown; it must not run on
                # an ungracefully-powered-down node (that requires ungracefulPowerUp)
                if {$ugpd($t)} {
                    lappend errors \
                        "VIOLATION: 'powerUp' on '$t' while ungracefully powered down  (item=$item)"
                }
            } elseif {$action eq "ungracefulPowerUp"} {
                # ungracefulPowerUp is the recovery for ungracefulPowerDown;
                # it must not run on a powered-down node (that requires powerUp)
                if {$pd($t)} {
                    lappend errors \
                        "VIOLATION: 'ungracefulPowerUp' on '$t' while powered down  (item=$item)"
                }
            } else {
                # all other actions must not run on a node in any down state
                if {$pd($t)} {
                    lappend errors \
                        "VIOLATION: '$action' on '$t' while powered down  (item=$item)"
                }
                if {$ugpd($t)} {
                    lappend errors \
                        "VIOLATION: '$action' on '$t' while ungracefully powered down  (item=$item)"
                }
            }
        }

        # update power state
        switch -- $action {
            "powerDown"           { foreach t $targets { if {$t ne ""} { set pd($t)   1 } } }
            "powerUp"             { foreach t $targets { if {$t ne ""} { set pd($t)   0
                                                                          set ugpd($t) 0 } } }
            "ungracefulPowerDown" { foreach t $targets { if {$t ne ""} { set ugpd($t) 1 } } }
            "ungracefulPowerUp"   { foreach t $targets { if {$t ne ""} { set ugpd($t) 0
                                                                          set pd($t)   0 } } }
        }
    }
    return $errors
}

# ---------------------------------------------------------------------------
# Action list generation — mirrors the fixed chaotic block exactly
# ---------------------------------------------------------------------------
proc GenerateActionList {} {
    set allTargetsList {primary backup monitor}

    set MAX_ACTIONS_BEFORE_CHECK 30
    set MAX_ACTIONS_TOTAL        200
    set MIN_SLEEP                1
    set MAX_SLEEP                30

    # build _doActionList (chaoticSubset "all", no external-disk or netem)
    set _doActionList {}
    foreach _a {powerDown ungracefulPowerDown redundancyDisable
                redundancyServiceDisable reload linkNetemAdd consulDown cpuHog} {
        foreach _t1 {primary backup monitor} {
            lappend _doActionList "${_a}:${_t1}:"
        }
    }
    foreach _t1 {monitor} {
        lappend _doActionList "isolateNode:${_t1}:"
    }
    foreach _a {messageSpoolDisable mateLinkServiceDisable
                messageBackboneServiceDisable} {
        foreach _t1 {primary backup} {
            lappend _doActionList "${_a}:${_t1}:"
        }
    }
    foreach _a {linkDown consulLinkDown} {
        foreach _t1 {primary backup} {
            foreach _t2 {primary backup} {
                if {$_t1 ne $_t2 &&
                    [lsearch $_doActionList "${_a}:${_t2}-${_t1}:"] == -1} {
                    lappend _doActionList "${_a}:${_t1}-${_t2}:"
                }
            }
        }
    }
    foreach _t1 {primary backup} {
        foreach _t2 {primary backup} {
            if {$_t1 ne $_t2 &&
                [lsearch $_doActionList "mateLinkDown:${_t2}-${_t1}:"] == -1} {
                lappend _doActionList "mateLinkDown:${_t1}-${_t2}:"
            }
        }
    }
    lappend _doActionList "reload:primary-backup-monitor:"

    array set UNDO {
        isolateNode                   recoverNode
        powerDown                     powerUp
        ungracefulPowerDown           ungracefulPowerUp
        reload                        {}
        cpuHog                        {}
        linkDown                      linkUp
        mateLinkDown                  mateLinkUp
        consulLinkDown                consulLinkUp
        messageSpoolDisable           messageSpoolEnable
        redundancyDisable             redundancyEnable
        messageBackboneServiceDisable messageBackboneServiceEnable
        mateLinkServiceDisable        mateLinkServiceEnable
        redundancyServiceDisable      redundancyServiceEnable
        linkNetemAdd                  linkNetemRemove
        consulDown                    consulUp
    }

    set actionList        {}
    set listOfActionsNumber 0

    while {[llength $actionList] <= $MAX_ACTIONS_TOTAL} {

        set _currentActionList {}

        while {[llength $_currentActionList] <= $MAX_ACTIONS_BEFORE_CHECK} {

            set _currentDo [lindex [lshuffle $_doActionList] \
                                [expr {int(rand()*[llength $_doActionList])}]]
            set _currentDoAction     [lindex [split $_currentDo :] 0]
            set _currentDoTargetList [lindex [split $_currentDo :] 1]
            set _currentDoValue      [lindex [split $_currentDo :] 2]
            set _currentUndoAction   $UNDO($_currentDoAction)

            array set _powerDownFlag           {}
            array set _nodeIsolationFlag       {}
            array set _ungracefulPowerDownFlag {}
            array set _diskDownFlag            {}
            array set _skipThisIndex           {}

            foreach _currentDoTarget [split $_currentDoTargetList -] {
                set _powerDownFlag($_currentDoTarget)           0
                set _nodeIsolationFlag($_currentDoTarget)       0
                set _ungracefulPowerDownFlag($_currentDoTarget) 0
                set _diskDownFlag($_currentDoTarget)            0
                set _skipThisIndex($_currentDoTarget)           0
            }

            # DO scan: check FIRST (before updating flags), then update.
            # linsert at position _x places the new element BEFORE the action
            # at _x, so it runs in the state from actions 0.._x-1 — which is
            # what the flags represent at the point the check is made.
            set _allowedDoIndexList {}
            for {set _x 0} {$_x < [llength $_currentActionList]} {incr _x +1} {

                set _item       [lindex $_currentActionList $_x]
                set _action     [lindex [split $_item :]      0]
                set _targetList [lindex [split $_item :]      1]

                # below we enforce the rules
                 if {$_currentDoAction == "powerDown"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t) == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_powerDownFlag($_t) == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} {
                        if {[HasActionOnTargetBeforeRecovery \
                                $_currentActionList $_x \
                                $_currentDoTargetList "powerUp"]} {
                            set _allowed 0
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == "ungracefulPowerDown"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t) == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_powerDownFlag($_t) == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} {
                        if {[HasActionOnTargetBeforeRecovery \
                                $_currentActionList $_x \
                                $_currentDoTargetList "ungracefulPowerUp"]} {
                            set _allowed 0
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == "reload"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t) == 1 || \
                            $_powerDownFlag($_t) == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_diskDownFlag($_t) == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == "externalDiskLinkDown"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t) == 1 || \
                            $_diskDownFlag($_t) == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == "redundancyDisable"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t)           == 1 || \
                            $_powerDownFlag($_t)           == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_nodeIsolationFlag($_t)       == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == "messageBackboneServiceDisable"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t)           == 1 || \
                            $_powerDownFlag($_t)           == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_nodeIsolationFlag($_t)       == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == "redundancyServiceDisable"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t)           == 1 || \
                            $_powerDownFlag($_t)           == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_nodeIsolationFlag($_t)       == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == "messageSpoolDisable"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t)           == 1 || \
                            $_powerDownFlag($_t)           == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_nodeIsolationFlag($_t)       == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == "linkDown"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t)           == 1 || \
                            $_powerDownFlag($_t)           == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_nodeIsolationFlag($_t)       == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == "mateLinkServiceDisable"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t)           == 1 || \
                            $_powerDownFlag($_t)           == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_nodeIsolationFlag($_t)       == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == "mateLinkDown"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t)           == 1 || \
                            $_powerDownFlag($_t)           == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_nodeIsolationFlag($_t)       == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                } elseif {$_currentDoAction == ""} {
                    # do nothing
                } else {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t)           == 1 || \
                            $_powerDownFlag($_t)           == 1 || \
                            $_nodeIsolationFlag($_t)       == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
                }

                # below we set the flags based on the action at _x
                if {$_action == "powerDown"} {
                    foreach _target [split $_targetList -] {
                        set _powerDownFlag($_target) 1
                        set _skipThisIndex($_target) 0
                    }
                } elseif {$_action == "powerUp"} {
                    foreach _target [split $_targetList -] {
                        set _powerDownFlag($_target) 0
                        set _skipThisIndex($_target) 1
                    }
                } elseif {$_action == "ungracefulPowerDown"} {
                    foreach _target [split $_targetList -] {
                        set _ungracefulPowerDownFlag($_target) 1
                        set _skipThisIndex($_target) 0
                    }
                } elseif {$_action == "ungracefulPowerUp"} {
                    foreach _target [split $_targetList -] {
                        set _ungracefulPowerDownFlag($_target) 0
                        set _skipThisIndex($_target) 1
                    }
                } elseif {$_action == "messageSpoolDisable" ||
                           $_action == "redundancyDisable" ||
                           $_action == "messageBackboneServiceDisable" ||
                           $_action == "redundancyServiceDisable" ||
                           $_action == "linkDown" ||
                           $_action == "mateLinkServiceDisable" ||
                           $_action == "mateLinkDown"} {
                    foreach _target $allTargetsList {
                        set _nodeIsolationFlag($_target) 1
                        set _skipThisIndex($_target) 0
                    }
                } elseif {$_action == "messageSpoolEnable" ||
                           $_action == "redundancyEnable" ||
                           $_action == "messageBackboneServiceEnable" ||
                           $_action == "redundancyServiceEnable" ||
                           $_action == "linkUp" ||
                           $_action == "mateLinkServiceEnable" ||
                           $_action == "mateLinkUp"} {
                    foreach _target $allTargetsList {
                        set _nodeIsolationFlag($_target) 0
                        set _skipThisIndex($_target) 1
                    }
                } elseif {$_action == "externalDiskLinkDown"} {
                    foreach _target [split $_targetList -] {
                        set _diskDownFlag($_target) 1
                        set _skipThisIndex($_target) 0
                    }
                } elseif {$_action == "externalDiskLinkUp"} {
                    foreach _target [split $_targetList -] {
                        set _diskDownFlag($_target) 0
                        set _skipThisIndex($_target) 1
                    }
                } else {
                    foreach _target [split $_targetList -] {
                        set _skipThisIndex($_target) 0
                    }
                }
            }
            # After the loop _x == llength(_currentActionList): check append at end
             if {$_currentDoAction == "powerDown"} {
                set _allowed 1
                foreach _t [split $_currentDoTargetList -] {
                    if {$_skipThisIndex($_t) == 1 || \
                        $_ungracefulPowerDownFlag($_t) == 1 || \
                        $_powerDownFlag($_t) == 1} {
                            set _allowed 0
                            break
                    }
                }
                if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
            } elseif {$_currentDoAction == "ungracefulPowerDown"} {
                set _allowed 1
                foreach _t [split $_currentDoTargetList -] {
                    if {$_skipThisIndex($_t) == 1 || \
                        $_ungracefulPowerDownFlag($_t) == 1 || \
                        $_powerDownFlag($_t) == 1} {
                            set _allowed 0
                            break
                    }
                }
                if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
            } elseif {$_currentDoAction == "reload"} {
                set _allowed 1
                foreach _t [split $_currentDoTargetList -] {
                    if {$_skipThisIndex($_t) == 1 || \
                        $_powerDownFlag($_t) == 1 || \
                        $_ungracefulPowerDownFlag($_t) == 1 || \
                        $_diskDownFlag($_t) == 1} {
                            set _allowed 0
                            break
                    }
                }
                if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
            } elseif {$_currentDoAction == "externalDiskLinkDown"} {
                set _allowed 1
                foreach _t [split $_currentDoTargetList -] {
                    if {$_skipThisIndex($_t) == 1 || \
                        $_diskDownFlag($_t) == 1} {
                            set _allowed 0
                            break
                    }
                }
                if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
            } elseif {$_currentDoAction == "redundancyDisable" || \
                       $_currentDoAction == "messageBackboneServiceDisable" || \
                       $_currentDoAction == "redundancyServiceDisable" || \
                       $_currentDoAction == "messageSpoolDisable" || \
                       $_currentDoAction == "linkDown" || \
                       $_currentDoAction == "mateLinkServiceDisable" || \
                       $_currentDoAction == "mateLinkDown"} {
                set _allowed 1
                foreach _t [split $_currentDoTargetList -] {
                    if {$_skipThisIndex($_t)           == 1 || \
                        $_powerDownFlag($_t)           == 1 || \
                        $_ungracefulPowerDownFlag($_t) == 1 || \
                        $_nodeIsolationFlag($_t)       == 1} {
                            set _allowed 0
                            break
                    }
                }
                if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
            } elseif {$_currentDoAction == ""} {
                # do nothing
            } else {
                set _allowed 1
                foreach _t [split $_currentDoTargetList -] {
                    if {$_skipThisIndex($_t)           == 1 || \
                        $_powerDownFlag($_t)           == 1 || \
                        $_nodeIsolationFlag($_t)       == 1 || \
                        $_ungracefulPowerDownFlag($_t) == 1} {
                            set _allowed 0
                            break
                    }
                }
                if {$_allowed == 1} { lappend _allowedDoIndexList $_x }
            }

            set _doIndex [lindex $_allowedDoIndexList \
                              [expr {int(rand()*[llength $_allowedDoIndexList])}]]
            if {$_doIndex == ""} {
                # No valid insertion point found — skip this action and retry
                # with a different one.
                continue
            }
            set _currentActionList [linsert $_currentActionList \
                                            $_doIndex \
                                            $_currentDo \
                                   ]

            # UNDO scan: find valid positions after the DO action
            array set _powerDownFlag           {}
            array set _nodeIsolationFlag       {}
            array set _ungracefulPowerDownFlag {}
            array set _diskDownFlag            {}
            array set _skipThisIndex           {}
            foreach _currentDoTarget [split $_currentDoTargetList -] {
                set _powerDownFlag($_currentDoTarget)           0
                set _nodeIsolationFlag($_currentDoTarget)       0
                set _ungracefulPowerDownFlag($_currentDoTarget) 0
                set _diskDownFlag($_currentDoTarget)            0
                set _skipThisIndex($_currentDoTarget)           0
            }

            set _allowedUndoIndexList {}
            for {set _y [expr {$_doIndex + 1}]} \
                {$_y < [llength $_currentActionList]} {incr _y +1} {

                set _item       [lindex $_currentActionList $_y]
                set _action     [lindex [split $_item :] 0]
                set _targetList [lindex [split $_item :] 1]

                if {$_action == "powerDown"} {
                    foreach _target [split $_targetList -] {
                        set _powerDownFlag($_target) 1
                        set _skipThisIndex($_target) 0
                    }
                } elseif {$_action == "ungracefulPowerDown"} {
                    foreach _target [split $_targetList -] {
                        set _ungracefulPowerDownFlag($_target) 1
                        set _skipThisIndex($_target) 0
                    }
                } elseif {$_action == "powerUp"} {
                    foreach _target [split $_targetList -] {
                        set _powerDownFlag($_target) 0
                        set _skipThisIndex($_target) 1
                    }
                } elseif {$_action == "ungracefulPowerUp"} {
                    foreach _target [split $_targetList -] {
                        set _ungracefulPowerDownFlag($_target) 0
                        set _skipThisIndex($_target) 1
                    }
                } elseif {$_action == "redundancyDisable" ||
                           $_action == "redundancyServiceDisable" ||
                           $_action == "linkDown" ||
                           $_action == "mateLinkServiceDisable" ||
                           $_action == "mateLinkDown"} {
                    foreach _target [split $_targetList -] {
                        set _nodeIsolationFlag($_target) 1
                        set _skipThisIndex($_target) 0
                    }
                } elseif {$_action == "redundancyEnable" ||
                           $_action == "redundancyServiceEnable" ||
                           $_action == "linkUp" ||
                           $_action == "mateLinkServiceEnable" ||
                           $_action == "mateLinkUp"} {
                    foreach _target [split $_targetList -] {
                        set _nodeIsolationFlag($_target) 0
                        set _skipThisIndex($_target) 1
                    }
                } elseif {$_action == "externalDiskLinkDown"} {
                    foreach _target [split $_targetList -] {
                        set _diskDownFlag($_target) 1
                        set _skipThisIndex($_target) 0
                    }
                } elseif {$_action == "externalDiskLinkUp"} {
                    foreach _target [split $_targetList -] {
                        set _diskDownFlag($_target) 0
                        set _skipThisIndex($_target) 1
                    }
                } else {
                    foreach _target [split $_targetList -] {
                        set _skipThisIndex($_target) 0
                    }
                }

                if {$_currentUndoAction == "powerUp"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t) == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1 || \
                            $_powerDownFlag($_t) == 0 || \
                            $_diskDownFlag($_t) == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedUndoIndexList $_y }
                } elseif {$_currentUndoAction == "ungracefulPowerUp"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t) == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 0 || \
                            $_diskDownFlag($_t) == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedUndoIndexList $_y }
                } elseif {$_currentUndoAction == "externalDiskLinkUp"} {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t) == 1 || \
                            $_diskDownFlag($_t) == 0} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedUndoIndexList $_y }
                } elseif {$_currentDoAction == "reload" || $_currentDoAction == ""} {
                    # no undo needed
                } else {
                    set _allowed 1
                    foreach _t [split $_currentDoTargetList -] {
                        if {$_skipThisIndex($_t) == 1 || \
                            $_powerDownFlag($_t) == 1 || \
                            $_ungracefulPowerDownFlag($_t) == 1} {
                                set _allowed 0
                                break
                        }
                    }
                    if {$_allowed == 1} { lappend _allowedUndoIndexList $_y }
                }
            }

            set _undoIndex [lindex $_allowedUndoIndexList \
                                [expr {int(rand()*[llength $_allowedUndoIndexList])}]]
            if {$_currentUndoAction != ""} {
                if {$_undoIndex != ""} {
                    set _currentActionList [linsert $_currentActionList \
                                                    $_undoIndex \
                                                    $_currentUndoAction:$_currentDoTargetList:$_currentDoValue \
                                           ]
                } else {
                    set _currentActionList [linsert $_currentActionList \
                                                    [expr $_doIndex + 1] \
                                                    $_currentUndoAction:$_currentDoTargetList:$_currentDoValue \
                                           ]
                }
            }
        }

        foreach _element $_currentActionList {
            set _sleep [expr {$MIN_SLEEP + int(($MAX_SLEEP - $MIN_SLEEP) * rand())}]
            lappend actionList $_element
            lappend actionList "sleep::${_sleep}"
        }
        incr listOfActionsNumber
        lappend actionList "check::${listOfActionsNumber}"
    }

    return $actionList
}

# ---------------------------------------------------------------------------
# Main: run many trials and report
# ---------------------------------------------------------------------------
set trials    1000
set seed      [clock clicks]
expr {srand($seed)}
puts "Running $trials trials (seed=$seed) ..."

set violations 0
set totalActions 0

for {set i 1} {$i <= $trials} {incr i} {
    set al [GenerateActionList]
    incr totalActions [llength $al]
    set errs [ValidateActionList $al]
    if {[llength $errs] > 0} {
        incr violations [llength $errs]
        puts "Trial $i: [llength $errs] violation(s):"
        foreach e $errs { puts "  $e" }
        puts "  Action list:"
        foreach entry $al { puts "    $entry" }
        if {$violations >= 10} {
            puts "(stopping after 10 violations)"
            break
        }
    }
}

if {$violations == 0} {
    puts "OK — $trials trials, $totalActions total entries, 0 violations."
} else {
    puts "FAIL — $violations violation(s) found."
    exit 1
}
