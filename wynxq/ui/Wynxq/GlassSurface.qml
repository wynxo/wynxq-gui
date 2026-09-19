import QtQuick
import QtQuick.Window
import QtQuick.Effects

/*!
    Wynxq's interaction-only glass material.

    Permanent chrome stays opaque. Floating/open surfaces can additionally opt
    into a live GPU backdrop blur. This is the closest cross-platform analogue
    to the optical part of Apple's material without depending on macOS-only APIs.
*/
Rectangle {
    id: surface

    property color tint: Theme.glassTint
    property real fillOpacity: Theme.glassOpacity
    property bool solid: true
    property bool glassEnabled: false
    property bool autoGlass: true
    property bool backdropBlur: false
    // Only accept an explicit scene that excludes this surface. Sampling the
    // window content also samples its popups, creating a feedback loop.
    property Item backdropItem: null
    property real blurAmount: 0.72
    property bool elevated: false
    property bool active: false
    property bool strongEdge: false
    property bool sheen: true
    property bool outlineVisible: true
    property color edgeColor: active ? Theme.accentEdge
                                     : strongEdge ? Theme.glassEdgeStrong : Theme.borderSubtle

    readonly property real clampedFill: Math.max(0, Math.min(1, fillOpacity))
    readonly property bool autoInteractionGlass: autoGlass && (
        (tint === Theme.glassTintHover && clampedFill > 0)
        || (elevated && clampedFill >= 0.9)
        || (strongEdge && clampedFill > 0 && clampedFill < 0.5)
    )
    readonly property bool materialOn: glassEnabled || autoInteractionGlass
    readonly property bool opaqueIdle: solid && (
        clampedFill >= 0.66
        || (tint === Theme.glassTint && clampedFill >= Theme.glassThinOpacity)
    )
    readonly property bool liveBlurOn: materialOn && backdropBlur && backdropItem !== null
        && GraphicsInfo.api !== GraphicsInfo.Software
    readonly property var hostContent: liveBlurOn ? backdropItem : null
    readonly property point backdropOrigin: hostContent
        ? surface.mapToItem(hostContent, 0, 0)
        : Qt.point(0, 0)

    antialiasing: true
    color: liveBlurOn ? "transparent"
         : solid && elevated ? tint
         : materialOn ? Theme.alpha(tint, clampedFill)
         : opaqueIdle ? tint : Theme.alpha(tint, clampedFill)
    border.width: outlineVisible ? 1 : 0
    border.color: edgeColor

    Behavior on color {
        enabled: !Theme.reducedMotion
        ColorAnimation { duration: Theme.fast }
    }
    Behavior on border.color {
        enabled: !Theme.reducedMotion
        ColorAnimation { duration: Theme.fast }
    }

    // Inactive controls allocate no capture texture or blur pipeline. The
    // source must be a separate scene, never an ancestor of this surface.
    Loader {
        anchors.fill: parent
        z: -4
        active: surface.liveBlurOn
        sourceComponent: Item {
            ShaderEffectSource {
                id: backdropSource
                visible: false
                sourceItem: surface.hostContent
                sourceRect: Qt.rect(surface.backdropOrigin.x, surface.backdropOrigin.y,
                                    Math.max(1, surface.width), Math.max(1, surface.height))
                textureSize: Qt.size(Math.max(1, Math.round(surface.width)),
                                     Math.max(1, Math.round(surface.height)))
                live: true
                recursive: false
                smooth: true
            }
            Rectangle {
                id: roundedMask
                anchors.fill: parent
                radius: surface.radius
                color: "white"
                layer.enabled: true
                visible: false
            }
            MultiEffect {
                anchors.fill: parent
                source: backdropSource
                blurEnabled: true
                blur: surface.blurAmount
                blurMax: 48
                saturation: 0.18
                brightness: 0.035
                maskEnabled: true
                maskSource: roundedMask
                autoPaddingEnabled: false
            }
        }
    }

    // Keep text legible even above high-contrast content. Optical details stay
    // in the edges; background text should never compete with popup controls.
    Rectangle {
        anchors.fill: parent
        z: -3
        radius: surface.radius
        visible: surface.liveBlurOn
        color: Theme.alpha(surface.tint, Math.max(0.92, surface.clampedFill))
    }

    Rectangle {
        z: -8
        x: -7; y: 4
        width: surface.width + 14; height: surface.height + 10
        radius: surface.radius + 7
        color: Theme.alpha(Theme.glassShadow, 0.08)
        opacity: surface.materialOn && surface.elevated ? 1 : 0
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
    }
    Rectangle {
        z: -7
        x: -4; y: 3
        width: surface.width + 8; height: surface.height + 6
        radius: surface.radius + 4
        color: Theme.alpha(Theme.glassShadow, 0.13)
        opacity: surface.materialOn && surface.elevated ? 1 : 0
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
    }
    Rectangle {
        z: -6
        x: -1; y: 2
        width: surface.width + 2; height: surface.height + 2
        radius: surface.radius + 2
        color: Theme.alpha(Theme.glassShadow, 0.20)
        opacity: surface.materialOn && surface.elevated ? 1 : 0
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
    }

    // Wide curved highlight plus a tight top-edge sparkle sells the refractive
    // read even on platforms where compositor blur is less pronounced.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 1
        height: Math.min(surface.height - 2, Math.max(surface.radius * 1.7, Math.round(surface.height * 0.50)))
        radius: Math.max(0, surface.radius - 1)
        opacity: surface.materialOn && surface.sheen ? 1 : 0
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
        gradient: Gradient {
            GradientStop { position: 0.0; color: surface.active ? Theme.glassSpecularHot : Theme.glassSpecular }
            GradientStop { position: 0.30; color: Theme.alpha(Theme.textPrimary, 0.065) }
            GradientStop { position: 0.70; color: Theme.alpha(Theme.textPrimary, 0.014) }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: Math.max(0, surface.radius - 1)
        color: "transparent"
        border.width: 1
        border.color: Theme.glassInner
        opacity: surface.materialOn ? 1 : 0
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: Math.max(3, Math.round(surface.radius * 0.46))
        anchors.rightMargin: Math.max(3, Math.round(surface.radius * 0.46))
        height: 1
        color: surface.active ? Theme.glassSpecularHot : Theme.glassSpecular
        opacity: surface.materialOn && surface.sheen ? 0.86 : 0
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: Math.max(4, Math.round(surface.radius * 0.7))
        anchors.rightMargin: Math.max(4, Math.round(surface.radius * 0.7))
        height: 1
        color: Theme.glassLowlight
        opacity: surface.materialOn ? 0.58 : 0
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
    }
}
